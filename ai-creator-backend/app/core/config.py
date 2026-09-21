from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Creator API"
    app_env: str = "development"
    api_prefix: str = "/v1"
    database_url: str = "sqlite:///./data/app.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "development-secret-change-me"
    jwt_expire_minutes: int = 60 * 24 * 7
    admin_username: str = "admin"
    admin_password: str = "change-me-before-deploy"
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    clipcat_api_key: str = ""
    clipcat_base_url: str = "https://clipcat.ai"
    clipcat_bin: str = "clipcat"
    hot_products_timezone: str = "Asia/Shanghai"
    hot_products_region: str = "US"
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_public_base_url: str = ""
    upload_dir: str = "data"
    mock_external_services: bool = True
    celery_always_eager: bool = True
    allowed_origins: str = "http://localhost:5173"
    max_context_rounds: int = 20
    system_prompt: str = "你是一个安全、准确、友好的 AI 助手。"
    upload_max_bytes: int = 20 * 1024 * 1024

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def wechat_configured(self) -> bool:
        return bool(self.wechat_app_id and self.wechat_app_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
