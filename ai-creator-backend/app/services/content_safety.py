import httpx

from app.core.config import settings


class ContentRejected(Exception):
    pass


class ContentSafetyService:
    """Pre-flight text checker. Media callbacks can be added without changing callers."""

    async def check_text(self, openid: str, content: str, scene: int = 2) -> None:
        if settings.mock_external_services or not settings.wechat_configured:
            if any(word in content.lower() for word in ("__reject__", "测试违禁词")):
                raise ContentRejected("内容安全检测未通过")
            return
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"https://api.weixin.qq.com/wxa/msg_sec_check?access_token={token}",
                json={"content": content, "version": 2, "scene": scene, "openid": openid},
            )
            response.raise_for_status()
            data = response.json()
        if data.get("errcode") or data.get("result", {}).get("suggest") != "pass":
            raise ContentRejected(data.get("errmsg", "内容安全检测未通过"))

    async def _access_token(self) -> str:
        if not settings.wechat_app_id or not settings.wechat_app_secret:
            raise RuntimeError("微信内容安全配置缺失")
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://api.weixin.qq.com/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": settings.wechat_app_id,
                    "secret": settings.wechat_app_secret,
                },
            )
            response.raise_for_status()
        data = response.json()
        if "access_token" not in data:
            raise RuntimeError(data.get("errmsg", "无法获取微信 access_token"))
        return data["access_token"]


content_safety = ContentSafetyService()

