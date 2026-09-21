import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db


password_hasher = PasswordHasher()


def hash_password(value: str) -> str:
    return password_hasher.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    try:
        return password_hasher.verify(hashed, value)
    except Exception:
        return False


def create_token(subject: str, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, expected_type: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if payload.get("type") != expected_type:
            raise InvalidTokenError("wrong token type")
        return str(payload["sub"])
    except (InvalidTokenError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效") from exc


def get_current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)):
    from app.models import User

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    user_id = decode_token(authorization[7:], "user")
    user = db.get(User, user_id)
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return user


def get_optional_user(authorization: str = Header(default=""), db: Session = Depends(get_db)):
    from app.models import User

    if not authorization.startswith("Bearer "):
        return None
    try:
        user_id = decode_token(authorization[7:], "user")
    except HTTPException:
        return None
    user = db.get(User, user_id)
    if not user or user.status != "active":
        return None
    return user


def get_current_admin(
    request: Request,
    admin_session: str | None = Cookie(default=None),
    x_csrf_token: str | None = Header(default=None),
    csrf_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    from app.models import AdminUser

    if not admin_session:
        raise HTTPException(status_code=401, detail="请先登录管理端")
    admin_id = decode_token(admin_session, "admin")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not csrf_token or not x_csrf_token or not secrets.compare_digest(csrf_token, x_csrf_token):
            raise HTTPException(status_code=403, detail="CSRF 校验失败")
    admin = db.get(AdminUser, admin_id)
    if not admin or not admin.is_active:
        raise HTTPException(status_code=401, detail="管理员不存在或已停用")
    return admin

