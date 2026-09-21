from sqlalchemy import inspect, select, text

from app.core.config import settings
from app.core.db import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models import AIProduct, AdminUser, Asset, GenerationTask, RechargePackage, TaskStatus, utcnow
from app.services.providers import IMAGE_ASPECT_RATIOS
from app.services.wallet import capture


def ensure_user_auth_schema() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("users")}
    index_names = {index["name"] for index in inspector.get_indexes("users")}
    statements = []
    if "username" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN username VARCHAR(80)")
    if "password_hash" not in columns:
        statements.append("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        if "ix_users_username" not in index_names:
            try:
                connection.execute(text("CREATE UNIQUE INDEX ix_users_username ON users (username)"))
            except Exception:
                pass


def ensure_generation_soft_delete_schema() -> None:
    inspector = inspect(engine)
    if "generation_tasks" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("generation_tasks")}
    if "deleted_at" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE generation_tasks ADD COLUMN deleted_at DATETIME NULL"))


def ensure_recharge_order_schema() -> None:
    inspector = inspect(engine)
    if "recharge_orders" not in inspector.get_table_names():
        return
    columns = {column["name"]: column for column in inspector.get_columns("recharge_orders")}
    package = columns.get("package_id")
    if not package or package.get("nullable"):
        return
    if engine.dialect.name == "sqlite":
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE recharge_orders MODIFY package_id VARCHAR(32) NULL"))


def initialize_database() -> None:
    if settings.app_env == "production":
        if settings.jwt_secret == "development-secret-change-me":
            raise RuntimeError("生产环境必须配置 JWT_SECRET")
        if settings.admin_password == "change-me-before-deploy":
            raise RuntimeError("生产环境必须配置 ADMIN_PASSWORD")
    if settings.app_env != "production":
        Base.metadata.create_all(bind=engine)
        ensure_user_auth_schema()
        ensure_generation_soft_delete_schema()
        ensure_recharge_order_schema()
    with SessionLocal() as db:
        if not db.scalar(select(AdminUser).where(AdminUser.username == settings.admin_username)):
            db.add(AdminUser(username=settings.admin_username, password_hash=hash_password(settings.admin_password)))
        if not db.scalar(select(AIProduct.id).limit(1)):
            db.add_all([
                AIProduct(name="AI 方图", feature_type="image", provider="clipcat", model="default",
                          points_cost=10, config={"aspect_ratios": list(IMAGE_ASPECT_RATIOS), "max_supplier_credits": 20}),
                AIProduct(name="视频生成", feature_type="video", provider="clipcat", model="seedance2",
                          points_cost=80, config={"duration": 10, "resolution": "480p", "aspect_ratio": "9:16",
                                                 "language": "zh", "max_supplier_credits": 80}),
                AIProduct(name="DeepSeek 对话", feature_type="chat", provider="deepseek", model="deepseek-flash",
                          points_cost=1, config={}),
            ])
        else:
            for product in db.scalars(select(AIProduct)).all():
                if product.feature_type == "chat":
                    if product.provider == "deepseek" and product.model in {
                        "", "deepseek-chat", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp",
                    }:
                        product.model = "deepseek-flash"
                    continue
                if (product.feature_type == "video" and product.provider == "clipcat"
                        and product.name == "商品短视频"):
                    product.name = "视频生成"
                if (product.feature_type == "video" and product.provider == "clipcat"
                        and product.model in {"grok_imagine", "seedance2_mini"}):
                    product.model = "seedance2"
                config = dict(product.config or {})
                changed = False
                if "max_supplier_credits" not in config:
                    config["max_supplier_credits"] = 20 if product.feature_type == "image" else 80
                    changed = True
                if product.feature_type == "image" and config.get("aspect_ratios") != list(IMAGE_ASPECT_RATIOS):
                    config["aspect_ratios"] = list(IMAGE_ASPECT_RATIOS)
                    changed = True
                if changed:
                    product.config = config
        if settings.app_env != "production" and not db.scalar(select(RechargePackage.id).limit(1)):
            db.add_all([
                RechargePackage(name="体验包", amount_cents=100, points=100, bonus_points=0, sort_order=1),
                RechargePackage(name="创作包", amount_cents=1000, points=1000, bonus_points=100, sort_order=2),
            ])
        for asset in db.scalars(select(Asset).where(Asset.review_status == "pending", Asset.deleted_at.is_(None))):
            asset.review_status = "approved"
        for task in db.scalars(select(GenerationTask).where(GenerationTask.status == TaskStatus.PENDING_REVIEW.value)):
            capture(db, task.user_id, task.frozen_points, "generation", task.id)
            task.status = TaskStatus.SUCCEEDED.value
            task.completed_at = task.completed_at or utcnow()
        db.commit()
