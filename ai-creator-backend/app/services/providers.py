import asyncio
import json
import os
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import parse_qs, urlparse

import httpx

from app.core.config import settings
from app.services.storage import storage

# ClipCat `image --aspect-ratio` currently accepts only these values.
IMAGE_ASPECT_RATIOS = ("1:1", "16:9", "9:16")
IMAGE_ASPECT_RATIO_HINTS = {
    "1:1": "1:1 square 方图",
    "16:9": "16:9 landscape 横版",
    "9:16": "9:16 portrait 竖版",
}
YOGA_PRODUCT_NAME_OVERRIDES = {
    "1729596073113195136": "AirSlim 塑形高腰瑜伽裤",
    "1732548484494758886": "三条装高腰加绒保暖瑜伽裤",
    "1729410017419366654": "高腰加绒口袋保暖瑜伽裤",
    "1732617607618859907": "2.0 V 型腰线柔软高腰瑜伽裤",
    "1732067339613409435": "六条装高腰口袋运动瑜伽裤",
    "1732475372811424355": "三条装高腰收腹微喇瑜伽裤",
    "1731963384215474327": "多尺码加厚加绒高腰瑜伽裤",
    "1729560841401111015": "纯色高腰微喇修身瑜伽裤",
    "1732010666714174414": "天鹅绒加厚高腰口袋瑜伽裤",
    "1729485663226008830": "交叉腰微喇口袋瑜伽裤",
}

SOCIAL_VIDEO_HOSTS = (
    "tiktok.com", "douyin.com", "iesdouyin.com", "v.douyin.com",
    "vm.tiktok.com", "vt.tiktok.com",
)
SHORT_VIDEO_HOSTS = ("v.douyin.com", "vm.tiktok.com", "vt.tiktok.com")
DIRECT_VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".m4v")


def normalize_reference_video_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        raise ValueError("参考视频复刻需要视频链接")
    if text.startswith("clipcat://"):
        return text
    parsed = urlparse(text)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path or ""
    query = parse_qs(parsed.query)
    path_lower = path.lower()
    if path_lower.endswith(DIRECT_VIDEO_SUFFIXES):
        return text
    modal_id = (query.get("modal_id") or query.get("video_id") or [None])[0]
    if modal_id and modal_id.isdigit() and any(host.endswith(item) for item in ("douyin.com", "iesdouyin.com")):
        return f"https://www.douyin.com/video/{modal_id}"
    douyin_video = re.search(r"(?:douyin\.com|iesdouyin\.com)(?:/share)?/video/(\d+)", text, re.I)
    if douyin_video:
        return f"https://www.douyin.com/video/{douyin_video.group(1)}"
    tiktok_video = re.search(r"tiktok\.com(?:/@[^/]+)?/video/(\d+)", text, re.I)
    if tiktok_video:
        return text
    if host in SHORT_VIDEO_HOSTS or (host.endswith("tiktok.com") and path_lower.startswith("/t/")):
        return text
    if "/search" in path_lower or host.endswith("douyin.com") or host.endswith("tiktok.com"):
        raise ValueError("请粘贴具体视频的分享链接，不要使用搜索页或个人主页链接")
    if parsed.scheme in {"http", "https"}:
        return text
    raise ValueError("参考视频链接无效，请使用抖音/TikTok 分享链接或视频直链")


def is_social_reference_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(host in lowered for host in SOCIAL_VIDEO_HOSTS)


def friendly_clipcat_error(message: str) -> str:
    text = (message or "").strip()
    lowered = text.lower()
    if "status 520" in lowered or "error code: 520" in lowered:
        return "参考视频链接无法解析。请打开抖音/TikTok 视频播放页后复制分享链接，不要粘贴搜索结果页"
    if "item_image is required" in lowered or "--image or --image-url is required" in lowered:
        return "Clipcat 未收到商品图，请重新上传替换素材后再试"
    return text or "Clipcat CLI 执行失败"


@dataclass
class ProviderSubmission:
    provider_task_id: str | None
    status: str
    result_urls: list[str]
    raw: dict[str, Any]


class ClipcatProvider:
    """CLI boundary kept intentionally small so a REST adapter can replace it later."""

    def __init__(self) -> None:
        self._catalog_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._catalog_lock = threading.Lock()

    @staticmethod
    def image_prompt(prompt: str, aspect_ratio: str) -> str:
        ratio = aspect_ratio if aspect_ratio in IMAGE_ASPECT_RATIOS else "1:1"
        if ratio in prompt:
            return prompt
        hint = IMAGE_ASPECT_RATIO_HINTS[ratio]
        return f"{prompt.rstrip()}\n{hint}"

    def _bin(self) -> str:
        configured = settings.clipcat_bin or "clipcat"
        if os.path.isabs(configured) and os.path.isfile(configured):
            return configured
        found = shutil.which(configured)
        if found:
            return found
        fallback = os.path.expanduser("~/.local/bin/clipcat")
        if os.path.isfile(fallback):
            return fallback
        return configured

    def _run(self, args: list[str], timeout: int = 120, input_text: str | None = None) -> dict[str, Any]:
        import subprocess

        env = os.environ.copy()
        if settings.clipcat_api_key:
            env["CLIPCAT_API_KEY"] = settings.clipcat_api_key
        if settings.clipcat_base_url:
            env["CLIPCAT_BASE_URL"] = settings.clipcat_base_url
        process = subprocess.run(
            [self._bin(), *args], capture_output=True, text=True,
            timeout=timeout, env=env, check=False, input=input_text,
        )
        if process.returncode != 0:
            raise RuntimeError(friendly_clipcat_error(process.stderr.strip() or "Clipcat CLI 执行失败"))
        text = process.stdout.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
            if not match:
                raise RuntimeError("Clipcat 返回了无法识别的结果")
            return json.loads(match.group(1))

    def _catalog(self, raw: bool = False) -> dict[str, Any]:
        cache_key = "raw" if raw else "default"
        now = time.monotonic()
        with self._catalog_lock:
            cached = self._catalog_cache.get(cache_key)
            if cached and cached[0] > now:
                return cached[1]
        data = self._run(["models", "--raw"] if raw else ["models"])
        with self._catalog_lock:
            self._catalog_cache[cache_key] = (now + 60, data)
        return data

    @staticmethod
    def _yoga_brand(name: str) -> str:
        lowered = name.lower()
        for brand in ("Shapellx", "CHRLEISURE", "SHOWITTY", "ComfrtCore", "HIJESSE"):
            if brand.lower() in lowered:
                return brand
        return "TikTok 热销"

    @staticmethod
    def _yoga_category(name: str) -> str:
        lowered = name.lower()
        if any(word in lowered for word in ("fleece", "thermal", "velvet")):
            return "加绒保暖"
        if any(word in lowered for word in ("flare", "bootcut", "bell bottom")):
            return "微喇款"
        if any(word in lowered for word in ("shaping", "tummy control")):
            return "塑形款"
        if "pack" in lowered:
            return "组合装"
        if "pocket" in lowered:
            return "口袋款"
        return "高腰款"

    @staticmethod
    def _yoga_display_name(product_id: str, original_name: str) -> str:
        override = YOGA_PRODUCT_NAME_OVERRIDES.get(product_id)
        if override:
            return override
        lowered = original_name.lower()
        features = ["高腰"]
        if any(word in lowered for word in ("fleece", "thermal", "velvet")):
            features.append("加绒保暖")
        if any(word in lowered for word in ("shaping", "tummy control")):
            features.append("塑形收腹")
        if any(word in lowered for word in ("flare", "bootcut", "bell bottom")):
            features.append("微喇")
        if "pocket" in lowered:
            features.append("口袋")
        return "".join(dict.fromkeys(features)) + "瑜伽裤"

    def yoga_products(self, region: str = "US") -> dict[str, Any]:
        """Fetch and normalize the current hot TikTok Shop leggings selection."""
        if not settings.clipcat_api_key:
            raise RuntimeError("CLIPCAT_API_KEY 未配置")
        response = self._run([
            "product", "list",
            "--region", region,
            "--category-id", "601152",
            "--category-l2-id", "842376",
            "--category-l3-id", "601274",
            "--hot", "1",
            "--off-mark", "0",
            "--sort-field", "4",
            "--sort-type", "1",
            "--page", "1",
            "--page-size", "10",
        ])
        rows = response.get("data") or []
        if len(rows) < 10:
            raise RuntimeError(f"Clipcat 仅返回 {len(rows)} 个瑜伽裤爆品，保留上次成功榜单")
        ranked = sorted(rows, key=lambda row: int(row.get("total_sale_30d_cnt") or 0), reverse=True)[:10]
        products = []
        for rank, row in enumerate(ranked, 1):
            product_id = str(row.get("product_id") or "")
            original_name = str(row.get("product_name") or "瑜伽裤")
            products.append({
                "rank": rank,
                "product_id": product_id,
                "brand": self._yoga_brand(original_name),
                "name": self._yoga_display_name(product_id, original_name),
                "original_name": original_name,
                "category": self._yoga_category(original_name),
                "gmv_30d": float(row.get("total_sale_gmv_30d_amt") or 0),
                "sales_30d": int(row.get("total_sale_30d_cnt") or 0),
                "price": float(row.get("spu_avg_price") or 0),
                "rating": float(row.get("product_rating") or 0),
                "review_count": int(row.get("review_count") or 0),
            })
        last_crawl = max(int(row.get("last_crawl_dt") or 0) for row in ranked)
        data_date = str(last_crawl)
        if len(data_date) == 8:
            data_date = f"{data_date[:4]}-{data_date[4:6]}-{data_date[6:]}"
        return {
            "source": "TikTok Shop via Clipcat",
            "region": region,
            "category": "Leggings",
            "currency": response.get("currency") or "USD",
            "data_date": data_date,
            "products": products,
        }

    @staticmethod
    def _fallback_video_options(config: dict[str, Any]) -> dict[str, Any]:
        durations = config.get("durations") or [config.get("duration", 10)]
        resolutions = config.get("resolutions") or [config.get("resolution", "480p")]
        aspect_ratios = config.get("aspect_ratios") or [config.get("aspect_ratio", "9:16")]
        durations = sorted({int(value) for value in durations if value is not None})
        resolutions = list(dict.fromkeys(str(value) for value in resolutions if value))
        aspect_ratios = list(dict.fromkeys(str(value) for value in aspect_ratios if value))
        return {
            "duration": int(config.get("duration") or durations[0]),
            "resolution": str(config.get("resolution") or resolutions[0]),
            "aspect_ratio": str(config.get("aspect_ratio") or aspect_ratios[0]),
            "durations": durations,
            "resolutions": resolutions,
            "aspect_ratios": aspect_ratios,
            "combinations": [
                {"duration": duration, "resolution": resolution}
                for duration in durations for resolution in resolutions
            ],
        }

    def video_options(self, model: str, config: dict[str, Any]) -> dict[str, Any]:
        """Return the exact live Clipcat raw-video parameter combinations for a model."""
        fallback = self._fallback_video_options(config)
        if settings.mock_external_services or not settings.clipcat_api_key:
            return fallback
        catalog = self._catalog(raw=True)
        item = next(
            (row for row in catalog.get("models", []) if (row.get("value") or row.get("id")) == model),
            None,
        )
        if not item:
            raise RuntimeError("VIDEO_MODEL_UNAVAILABLE")
        combinations: list[dict[str, Any]] = []
        if item.get("durationType") == "discrete":
            for price in item.get("prices", []):
                combinations.append({
                    "duration": int(price["duration"]),
                    "resolution": str(price["resolution"]),
                    "supplier_credits": int(price["credits"]),
                })
        else:
            duration_range = item.get("durationRange") or {}
            minimum = int(duration_range["min"])
            maximum = int(duration_range["max"])
            for duration in range(minimum, maximum + 1):
                for resolution, credits_per_second in (item.get("creditsPerSecond") or {}).items():
                    combinations.append({
                        "duration": duration,
                        "resolution": str(resolution),
                        "supplier_credits": int(credits_per_second) * duration,
                    })
        if not combinations:
            raise RuntimeError("VIDEO_MODEL_OPTIONS_UNAVAILABLE")
        durations = sorted({row["duration"] for row in combinations})
        resolution_order = [str(value) for value in item.get("resolutions", [])]
        resolutions = [value for value in resolution_order if any(
            row["resolution"] == value for row in combinations
        )]
        aspect_ratios = [str(value) for value in item.get("aspectRatios", [])]
        if not aspect_ratios:
            raise RuntimeError("VIDEO_MODEL_OPTIONS_UNAVAILABLE")
        configured_duration = int(config.get("duration") or durations[0])
        duration = configured_duration if configured_duration in durations else durations[0]
        matching_resolutions = [
            row["resolution"] for row in combinations if row["duration"] == duration
        ]
        configured_resolution = str(config.get("resolution") or "")
        resolution = configured_resolution if configured_resolution in matching_resolutions else matching_resolutions[0]
        configured_ratio = str(config.get("aspect_ratio") or "")
        aspect_ratio = configured_ratio if configured_ratio in aspect_ratios else aspect_ratios[0]
        return {
            "duration": duration,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "durations": durations,
            "resolutions": resolutions,
            "aspect_ratios": aspect_ratios,
            "combinations": combinations,
        }

    def _materialize_image(self, url: str, temps: list[str]) -> str:
        value = str(url or "").strip()
        if value.startswith("mock://"):
            raise RuntimeError("商品图未实际上传，无法进行参考视频复刻")
        local = storage.local_path_for(value)
        if local:
            return local
        if value.startswith("http://") or value.startswith("https://"):
            suffix = os.path.splitext(value.split("?", 1)[0])[1] or ".jpg"
            handle, path = tempfile.mkstemp(suffix=suffix)
            os.close(handle)
            temps.append(path)
            with httpx.stream("GET", value, timeout=60, follow_redirects=True) as response:
                response.raise_for_status()
                with open(path, "wb") as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
            return path
        raise RuntimeError("不支持的商品图地址")

    def _append_images(self, args: list[str], urls: list[str], temps: list[str]) -> None:
        for url in urls:
            args.extend(["--image", self._materialize_image(url, temps)])

    def submit(self, feature_type: str, prompt: str, params: dict[str, Any]) -> ProviderSubmission:
        if settings.mock_external_services:
            suffix = "png" if feature_type == "image" else "mp4"
            return ProviderSubmission(
                provider_task_id=f"mock-{os.urandom(6).hex()}", status="succeeded",
                result_urls=[f"https://placehold.co/1024x1024.{suffix}?text=AI+Creator"],
                raw={"mock": True},
            )

        if not settings.clipcat_api_key:
            raise RuntimeError("CLIPCAT_API_KEY 未配置")
        temps: list[str] = []
        try:
            if feature_type == "image":
                expected = params.get("max_supplier_credits")
                if expected is None:
                    raise RuntimeError("PROVIDER_PRICE_POLICY_MISSING")
                catalog = self._run(["models"])
                image_models = catalog.get("imageModels") or catalog.get("image_models") or []
                selected = params.get("model")
                if selected and selected != "default":
                    matches = [item for item in image_models if (item.get("id") or item.get("model")) == selected]
                else:
                    matches = image_models[:1]
                if not matches:
                    raise RuntimeError("无法从 Clipcat 实时目录确认图片模型价格")
                quoted = matches[0].get("credits") or matches[0].get("creditsPerImage") or matches[0].get("cost")
                if quoted is None or int(quoted) > int(expected):
                    raise RuntimeError("PROVIDER_PRICE_CHANGED")
                aspect_ratio = params.get("aspect_ratio", "1:1")
                if aspect_ratio not in IMAGE_ASPECT_RATIOS:
                    aspect_ratio = "1:1"
                args = ["image", "--prompt", self.image_prompt(prompt, aspect_ratio), "--aspect-ratio", aspect_ratio]
                if params.get("model") and params["model"] != "default":
                    args.extend(["--model", params["model"]])
                self._append_images(args, params.get("image_urls") or [], temps)
                data = self._run(args)
            else:
                mode = params.get("generation_mode")
                if mode == "generate":
                    command = "generate"
                    args = [command, "--prompt-file", "-", "--model", params["model"],
                            "--duration", str(params["duration"]), "--resolution", params["resolution"],
                            "--size", params.get("aspect_ratio", "9:16")]
                else:
                    command = "replicate"
                    args = [command, "--prompt-file", "-", "--model", params["model"],
                            "--duration", str(params["duration"]), "--resolution", params["resolution"],
                            "--size", params.get("aspect_ratio", "9:16"), "--lang", params.get("language", "zh")]
                    if params.get("reference_video_url"):
                        args.extend(["--url", normalize_reference_video_url(params["reference_video_url"])])
                    self._append_images(args, params.get("image_urls") or [], temps)
                    if params.get("character_id"):
                        args.extend(["--character-id", str(params["character_id"])])
                expected = params.get("max_supplier_credits")
                if expected is None:
                    raise RuntimeError("PROVIDER_PRICE_POLICY_MISSING")
                args.extend(["--expected-credits", str(expected)])
                preview = self._run(args, input_text=prompt)
                confirm_id = preview.get("confirmId") or preview.get("confirm_id")
                quoted = preview.get("totalCredits") or preview.get("credits")
                if expected is not None and quoted is not None and int(quoted) > int(expected):
                    raise RuntimeError("PROVIDER_PRICE_CHANGED")
                if not confirm_id:
                    data = preview
                else:
                    data = self._run([command, "--confirm", str(confirm_id)])
            return self._normalize(data)
        finally:
            for path in temps:
                if os.path.exists(path):
                    os.unlink(path)

    def query(self, provider_task_id: str, feature_type: str, task_type: str | None = None) -> ProviderSubmission:
        if settings.mock_external_services:
            return ProviderSubmission(provider_task_id, "succeeded", [], {"mock": True})
        resolved_type = task_type or ("image" if feature_type == "image" else "product")
        return self._normalize(self._run(["query_task", "--task-id", provider_task_id, "--type", resolved_type]))

    @staticmethod
    def _normalize(data: dict[str, Any]) -> ProviderSubmission:
        if isinstance(data.get("data"), dict):
            data = {**data, **data["data"]}
        task_id = data.get("taskId") or data.get("task_id") or data.get("id")
        raw_status = str(data.get("status", "queued")).lower()
        status_map = {"completed": "succeeded", "success": "succeeded", "error": "failed"}
        status = status_map.get(raw_status, raw_status)
        urls: list[str] = []
        for key in ("url", "imageUrl", "videoUrl", "resultUrl"):
            if data.get(key):
                urls.append(data[key])
        for item in data.get("images", []) + data.get("videos", []):
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict):
                url = item.get("url") or item.get("videoUrl") or item.get("imageUrl")
                if url:
                    urls.append(url)
        return ProviderSubmission(str(task_id) if task_id else None, status, urls, data)


class DeepSeekProvider:
    async def stream(self, messages: list[dict[str, str]], model: str) -> AsyncIterator[str]:
        if settings.mock_external_services:
            answer = "这是模拟环境中的 AI 回复。配置新的 DeepSeek API Key 后即可连接真实模型。"
            for char in answer:
                yield char
                await asyncio.sleep(0.002)
            return
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置")
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.deepseek_api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "stream": True, "stream_options": {"include_usage": True}},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    data = json.loads(line[6:])
                    content = data.get("choices", [{}])[0].get("delta", {}).get("content")
                    if content:
                        yield content


clipcat = ClipcatProvider()
deepseek = DeepSeekProvider()
