import pytest

from app.core.config import settings
from app.services.providers import ClipcatProvider, normalize_reference_video_url


def test_clipcat_default_image_model_is_not_sent_as_literal_default(monkeypatch):
    provider = ClipcatProvider()
    calls = []

    def fake_run(args, timeout=120, input_text=None):
        calls.append((args, input_text))
        if args == ["models"]:
            return {"imageModels": [{"id": "gptimage2", "credits": 20}]}
        return {"taskId": "image-task", "status": "queued"}

    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "clipcat_api_key", "test-key")
    monkeypatch.setattr(provider, "_run", fake_run)

    provider.submit("image", "一只小猫", {
        "model": "default", "aspect_ratio": "1:1", "max_supplier_credits": 20,
    })

    image_args = calls[1][0]
    assert image_args[0] == "image"
    assert "--model" not in image_args
    assert image_args[image_args.index("--aspect-ratio") + 1] == "1:1"
    assert "1:1 square 方图" in image_args[image_args.index("--prompt") + 1]


def test_clipcat_image_keeps_existing_aspect_hint(monkeypatch):
    provider = ClipcatProvider()
    calls = []

    def fake_run(args, timeout=120, input_text=None):
        calls.append((args, input_text))
        if args == ["models"]:
            return {"imageModels": [{"id": "gptimage2", "credits": 20}]}
        return {"taskId": "image-task", "status": "queued"}

    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "clipcat_api_key", "test-key")
    monkeypatch.setattr(provider, "_run", fake_run)

    provider.submit("image", "9:16 portrait of a cat", {
        "model": "default", "aspect_ratio": "9:16", "max_supplier_credits": 20,
    })

    prompt = calls[1][0][calls[1][0].index("--prompt") + 1]
    assert prompt == "9:16 portrait of a cat"
    assert calls[1][0][calls[1][0].index("--aspect-ratio") + 1] == "9:16"


def test_clipcat_video_generation_uses_raw_generate_command(monkeypatch):
    provider = ClipcatProvider()
    calls = []

    def fake_run(args, timeout=120, input_text=None):
        calls.append((args, input_text))
        if args[0] == "generate" and "--confirm" not in args:
            return {"confirmId": "confirm-1", "totalCredits": 80}
        return {"taskId": "video-task", "status": "queued"}

    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "clipcat_api_key", "test-key")
    monkeypatch.setattr(provider, "_run", fake_run)

    result = provider.submit("video", "宇航员小猫在太空看地球", {
        "generation_mode": "generate", "model": "grok_imagine", "duration": 10,
        "resolution": "480p", "aspect_ratio": "9:16", "max_supplier_credits": 80,
    })

    submit_args, submit_prompt = calls[0]
    assert submit_args[0] == "generate"
    assert "--lang" not in submit_args
    assert "--image-url" not in submit_args
    assert submit_prompt == "宇航员小猫在太空看地球"
    assert calls[1][0] == ["generate", "--confirm", "confirm-1"]
    assert result.provider_task_id == "video-task"


def test_clipcat_replicate_sends_local_product_images(monkeypatch, tmp_path):
    image_path = tmp_path / "uploads" / "u1" / "product.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake-image")
    provider = ClipcatProvider()
    calls = []

    def fake_run(args, timeout=120, input_text=None):
        calls.append((args, input_text))
        if args[0] == "replicate" and "--confirm" not in args:
            return {"confirmId": "confirm-2", "totalCredits": 90}
        return {"taskId": "replicate-task", "status": "queued"}

    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "clipcat_api_key", "test-key")
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(provider, "_run", fake_run)

    result = provider.submit("video", "用我的商品复刻这条视频", {
        "generation_mode": "replicate",
        "model": "grok_imagine",
        "duration": 10,
        "resolution": "480p",
        "aspect_ratio": "9:16",
        "language": "zh",
        "reference_video_url": "https://www.tiktok.com/@u/video/1",
        "image_urls": ["local://uploads/u1/product.jpg"],
        "max_supplier_credits": 90,
    })

    submit_args, submit_prompt = calls[0]
    assert submit_args[0] == "replicate"
    assert "--image" in submit_args
    assert submit_args[submit_args.index("--image") + 1] == str(image_path)
    assert "--image-url" not in submit_args
    assert submit_args[submit_args.index("--url") + 1] == "https://www.tiktok.com/@u/video/1"
    assert submit_prompt == "用我的商品复刻这条视频"
    assert calls[1][0] == ["replicate", "--confirm", "confirm-2"]
    assert result.provider_task_id == "replicate-task"


def test_clipcat_replicate_rejects_mock_image_urls(monkeypatch):
    provider = ClipcatProvider()
    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "clipcat_api_key", "test-key")

    def fake_run(*args, **kwargs):
        raise AssertionError("should not run")

    monkeypatch.setattr(provider, "_run", fake_run)
    with pytest.raises(RuntimeError, match="商品图未实际上传"):
        provider.submit("video", "复刻", {
            "generation_mode": "replicate",
            "model": "grok_imagine",
            "duration": 10,
            "resolution": "480p",
            "aspect_ratio": "9:16",
            "reference_video_url": "https://www.tiktok.com/@u/video/1",
            "image_urls": ["mock://uploads/u1/a.jpg"],
            "max_supplier_credits": 90,
        })


def test_clipcat_raw_video_query_uses_raw_task_type(monkeypatch):
    provider = ClipcatProvider()
    calls = []

    def fake_run(args, timeout=120, input_text=None):
        calls.append(args)
        return {"taskId": "video-task", "status": "processing"}

    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(provider, "_run", fake_run)

    provider.query("video-task", "video", "raw")

    assert calls == [["query_task", "--task-id", "video-task", "--type", "raw"]]


def test_clipcat_video_options_exactly_match_live_raw_catalog(monkeypatch):
    provider = ClipcatProvider()

    def fake_run(args, timeout=120, input_text=None):
        assert args == ["models", "--raw"]
        return {"models": [{
            "value": "grok_imagine",
            "durationType": "discrete",
            "prices": [
                {"duration": 10, "resolution": "480p", "credits": 60},
                {"duration": 15, "resolution": "480p", "credits": 90},
                {"duration": 10, "resolution": "720p", "credits": 110},
            ],
            "resolutions": ["480p", "720p"],
            "aspectRatios": ["9:16", "16:9"],
        }]}

    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "clipcat_api_key", "test-key")
    monkeypatch.setattr(provider, "_run", fake_run)

    options = provider.video_options("grok_imagine", {
        "duration": 10,
        "resolution": "480p",
        "aspect_ratio": "9:16",
        "max_supplier_credits": 80,
    })

    assert options["durations"] == [10, 15]
    assert options["resolutions"] == ["480p", "720p"]
    assert options["aspect_ratios"] == ["9:16", "16:9"]
    assert options["combinations"] == [
        {"duration": 10, "resolution": "480p", "supplier_credits": 60},
        {"duration": 15, "resolution": "480p", "supplier_credits": 90},
        {"duration": 10, "resolution": "720p", "supplier_credits": 110},
    ]


def test_clipcat_yoga_products_are_ranked_by_30_day_sales(monkeypatch):
    provider = ClipcatProvider()
    rows = []
    for index, sales in enumerate([20, 80, 50, 90, 70, 10, 100, 40, 60, 30], 1):
        rows.append({
            "product_id": str(index),
            "product_name": f"Brand {index} High Waist Yoga Leggings with Pockets",
            "total_sale_30d_cnt": sales,
            "total_sale_gmv_30d_amt": sales * 20,
            "spu_avg_price": 20,
            "product_rating": 4.5,
            "review_count": index,
            "last_crawl_dt": 20260919,
        })

    monkeypatch.setattr(settings, "clipcat_api_key", "test-key")
    monkeypatch.setattr(provider, "_run", lambda args: {"currency": "USD", "data": rows})

    result = provider.yoga_products("US")

    assert [item["sales_30d"] for item in result["products"]] == sorted(
        [row["total_sale_30d_cnt"] for row in rows], reverse=True
    )
    assert result["data_date"] == "2026-09-19"
    assert result["products"][0]["rank"] == 1


def test_normalize_reference_video_url_rewrites_douyin_search_modal():
    source = (
        "https://www.douyin.com/search/%E5%B0%8Flin%E8%AF%B4"
        "?aid=c1a8e2d1-b6d0-46de-885e-7f627da63ab9"
        "&modal_id=7684053557896645888&type=general"
    )
    assert normalize_reference_video_url(source) == "https://www.douyin.com/video/7684053557896645888"


def test_normalize_reference_video_url_keeps_direct_and_short_links():
    assert normalize_reference_video_url("https://www.douyin.com/video/123") == "https://www.douyin.com/video/123"
    assert normalize_reference_video_url("https://www.tiktok.com/@u/video/123") == "https://www.tiktok.com/@u/video/123"
    assert normalize_reference_video_url("https://v.douyin.com/AbCde/") == "https://v.douyin.com/AbCde/"
    assert normalize_reference_video_url("https://cdn.example.com/a.mp4") == "https://cdn.example.com/a.mp4"


def test_normalize_reference_video_url_rejects_search_pages():
    with pytest.raises(ValueError, match="分享链接"):
        normalize_reference_video_url("https://www.douyin.com/search/%E5%B0%8Flin%E8%AF%B4")
