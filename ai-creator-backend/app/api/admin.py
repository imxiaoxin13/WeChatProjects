import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_token, get_current_admin, verify_password
from app.models import (
    AIProduct, AdminAuditLog, AdminUser, GenerationTask, PointAccount, RechargeOrder,
    RechargePackage, SystemSetting, User, utcnow,
)
from app.schemas import AdminLoginIn, PackageIn, PointAdjustIn, ProductIn, ProductPatch, SettingIn
from app.services.wallet import credit


router = APIRouter(prefix="/admin")


def audit(db: Session, admin: AdminUser, action: str, target_type: str, target_id: str, detail=None):
    db.add(AdminAuditLog(admin_id=admin.id, action=action, target_type=target_type,
                         target_id=target_id, detail=detail or {}))


@router.post("/auth/login")
def login(payload: AdminLoginIn, response: Response, db: Session = Depends(get_db)):
    admin = db.scalar(select(AdminUser).where(AdminUser.username == payload.username))
    now = utcnow()
    if admin and admin.locked_until and admin.locked_until > now:
        raise HTTPException(status_code=423, detail="登录失败次数过多，请稍后再试")
    if not admin or not admin.is_active or not verify_password(payload.password, admin.password_hash):
        if admin:
            admin.failed_login_attempts += 1
            if admin.failed_login_attempts >= 5:
                admin.locked_until = now + timedelta(minutes=15)
                admin.failed_login_attempts = 0
            db.commit()
        raise HTTPException(status_code=401, detail="账号或密码错误")
    admin.failed_login_attempts = 0
    admin.locked_until = None
    db.commit()
    secure = settings.app_env == "production"
    csrf = secrets.token_urlsafe(24)
    response.set_cookie("admin_session", create_token(admin.id, "admin"), httponly=True,
                        secure=secure, samesite="strict", max_age=settings.jwt_expire_minutes * 60)
    response.set_cookie("csrf_token", csrf, httponly=False, secure=secure, samesite="strict",
                        max_age=settings.jwt_expire_minutes * 60)
    return {"id": admin.id, "username": admin.username, "csrf_token": csrf}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie("admin_session")
    response.delete_cookie("csrf_token")
    return {"ok": True}


@router.get("/me")
def admin_me(admin: AdminUser = Depends(get_current_admin)):
    return {"id": admin.id, "username": admin.username}


@router.get("/dashboard")
def dashboard(admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    return {
        "users": db.scalar(select(func.count()).select_from(User)) or 0,
        "paid_orders": db.scalar(select(func.count()).select_from(RechargeOrder)
                                 .where(RechargeOrder.status == "paid")) or 0,
        "pending_orders": db.scalar(select(func.count()).select_from(RechargeOrder)
                                    .where(RechargeOrder.status == "pending")) or 0,
        "tasks": db.scalar(select(func.count()).select_from(GenerationTask)) or 0,
        "successful_tasks": db.scalar(select(func.count()).select_from(GenerationTask)
                                      .where(GenerationTask.status == "succeeded")) or 0,
        "consumed_points": db.scalar(select(func.coalesce(func.sum(GenerationTask.frozen_points), 0))
                                     .where(GenerationTask.status == "succeeded")) or 0,
    }


@router.get("/users")
def users(admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(User, PointAccount).join(PointAccount).order_by(User.created_at.desc()).limit(200)).all()
    return [{"id": user.id, "username": user.username, "nickname": user.nickname,
             "wechat_bound": bool(user.openid) and not user.openid.startswith("acct_"),
             "status": user.status, "balance": account.balance, "frozen": account.frozen,
             "created_at": user.created_at.isoformat()} for user, account in rows]


@router.post("/users/{user_id}/points")
def adjust_points(user_id: str, payload: PointAdjustIn, admin: AdminUser = Depends(get_current_admin),
                  db: Session = Depends(get_db)):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="首版人工调整仅支持加积分")
    if not db.get(User, user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    credit(db, user_id, payload.amount, "admin_adjust", admin.id, payload.idempotency_key, payload.note)
    audit(db, admin, "adjust_points", "user", user_id, {"amount": payload.amount, "note": payload.note})
    db.commit()
    return {"ok": True}


@router.get("/recharge-orders")
def orders(admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(RechargeOrder).order_by(RechargeOrder.created_at.desc()).limit(200)).all()
    return [{"id": row.id, "order_no": row.order_no, "user_id": row.user_id,
             "amount_cents": row.amount_cents, "points": row.points, "status": row.status,
             "created_at": row.created_at.isoformat()} for row in rows]


@router.post("/recharge-orders/{order_id}/approve")
def approve_order(order_id: str, admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    order = db.scalar(select(RechargeOrder).where(RechargeOrder.id == order_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == "paid":
        return {"ok": True, "idempotent": True}
    if order.status != "pending":
        raise HTTPException(status_code=409, detail="订单状态不可审核")
    credit(db, order.user_id, order.points, "recharge", order.id, f"recharge:{order.id}", "模拟充值到账")
    order.status = "paid"
    order.reviewed_by = admin.id
    order.reviewed_at = utcnow()
    audit(db, admin, "approve_recharge", "recharge_order", order.id, {"points": order.points})
    db.commit()
    return {"ok": True, "idempotent": False}


@router.post("/recharge-orders/{order_id}/reject")
def reject_order(order_id: str, admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    order = db.scalar(select(RechargeOrder).where(RechargeOrder.id == order_id).with_for_update())
    if not order or order.status != "pending":
        raise HTTPException(status_code=409, detail="订单状态不可驳回")
    order.status = "rejected"
    order.reviewed_by = admin.id
    order.reviewed_at = utcnow()
    audit(db, admin, "reject_recharge", "recharge_order", order.id)
    db.commit()
    return {"ok": True}


@router.get("/products")
def admin_products(admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(AIProduct).order_by(AIProduct.feature_type, AIProduct.points_cost)).all()
    return [{"id": row.id, "name": row.name, "feature_type": row.feature_type,
             "provider": row.provider, "model": row.model, "points_cost": row.points_cost,
             "config": row.config, "is_active": row.is_active} for row in rows]


@router.post("/products")
def create_product(payload: ProductIn, admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    row = AIProduct(**payload.model_dump())
    db.add(row)
    db.flush()
    audit(db, admin, "create_product", "ai_product", row.id, payload.model_dump())
    db.commit()
    return {"id": row.id}


@router.patch("/products/{product_id}")
def update_product(product_id: str, payload: ProductPatch, admin: AdminUser = Depends(get_current_admin),
                   db: Session = Depends(get_db)):
    row = db.get(AIProduct, product_id)
    if not row:
        raise HTTPException(status_code=404, detail="产品不存在")
    changes = payload.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(row, key, value)
    audit(db, admin, "update_product", "ai_product", row.id, changes)
    db.commit()
    return {"ok": True}


@router.get("/tasks")
def tasks(admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(GenerationTask).order_by(GenerationTask.created_at.desc()).limit(200)).all()
    return [{"id": row.id, "user_id": row.user_id, "feature_type": row.feature_type,
             "status": row.status, "prompt": row.prompt, "points": row.frozen_points,
             "provider_task_id": row.provider_task_id, "error_message": row.error_message,
             "created_at": row.created_at.isoformat()} for row in rows]


@router.get("/packages")
def packages(admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(RechargePackage).order_by(RechargePackage.sort_order)).all()
    return [{"id": row.id, "name": row.name, "amount_cents": row.amount_cents,
             "points": row.points, "bonus_points": row.bonus_points,
             "is_active": row.is_active, "sort_order": row.sort_order} for row in rows]


@router.post("/packages")
def create_package(payload: PackageIn, admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    row = RechargePackage(**payload.model_dump())
    db.add(row)
    db.flush()
    audit(db, admin, "create_package", "recharge_package", row.id, payload.model_dump())
    db.commit()
    return {"id": row.id}


@router.put("/packages/{package_id}")
def update_package(package_id: str, payload: PackageIn, admin: AdminUser = Depends(get_current_admin),
                   db: Session = Depends(get_db)):
    row = db.get(RechargePackage, package_id)
    if not row:
        raise HTTPException(status_code=404, detail="套餐不存在")
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    audit(db, admin, "update_package", "recharge_package", row.id, payload.model_dump())
    db.commit()
    return {"ok": True}


@router.get("/settings")
def get_settings(admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    return {row.key: row.value for row in db.scalars(select(SystemSetting)).all()}


@router.put("/settings/{key}")
def put_setting(key: str, payload: SettingIn, admin: AdminUser = Depends(get_current_admin), db: Session = Depends(get_db)):
    row = db.get(SystemSetting, key)
    if row:
        row.value = payload.value
    else:
        row = SystemSetting(key=key, value=payload.value)
        db.add(row)
    audit(db, admin, "update_setting", "system_setting", key, payload.value)
    db.commit()
    return {"ok": True}
