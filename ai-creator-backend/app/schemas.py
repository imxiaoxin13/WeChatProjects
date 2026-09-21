from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class WechatLoginIn(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class AccountRegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=6, max_length=64)
    nickname: str | None = Field(default=None, max_length=80)


class AccountLoginIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=64)


class ProfilePatchIn(BaseModel):
    nickname: str | None = Field(default=None, min_length=1, max_length=80)
    avatar_url: str | None = Field(default=None, max_length=500)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class GenerationIn(BaseModel):
    product_id: str | None = None
    prompt: str = Field(min_length=1, max_length=5000)
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ConversationIn(BaseModel):
    title: str = Field(default="新对话", max_length=120)


class ChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class RechargeOrderIn(BaseModel):
    amount_yuan: int = Field(ge=5, le=5000)
    idempotency_key: str = Field(min_length=8, max_length=128)


class AdminLoginIn(BaseModel):
    username: str
    password: str


class ProductIn(BaseModel):
    name: str
    feature_type: Literal["image", "video", "chat"]
    provider: str
    model: str
    points_cost: int = Field(gt=0)
    config: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ProductPatch(BaseModel):
    name: str | None = None
    model: str | None = None
    points_cost: int | None = Field(default=None, gt=0)
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class PointAdjustIn(BaseModel):
    amount: int
    note: str = Field(min_length=2, max_length=255)
    idempotency_key: str = Field(min_length=8, max_length=128)


class PackageIn(BaseModel):
    name: str
    amount_cents: int = Field(gt=0)
    points: int = Field(gt=0)
    bonus_points: int = Field(default=0, ge=0)
    is_active: bool = True
    sort_order: int = 0


class SettingIn(BaseModel):
    value: dict[str, Any]
