from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Asset, GenerationTask, SystemSetting, TaskStatus, utcnow
from app.services.providers import clipcat
from app.services.storage import storage
from app.services.wallet import capture, release
from app.workers.celery_app import celery_app


def _finish_success(db, task: GenerationTask, urls: list[str]) -> None:
    if task.status == TaskStatus.SUCCEEDED.value:
        return
    for url in urls:
        oss_key, external_url = storage.import_remote(task.user_id, task.id, url, task.feature_type)
        db.add(Asset(
            user_id=task.user_id,
            task_id=task.id,
            media_type=task.feature_type,
            oss_key=oss_key,
            external_url=external_url,
            review_status="approved",
        ))
    capture(db, task.user_id, task.frozen_points, "generation", task.id)
    task.status = TaskStatus.SUCCEEDED.value
    task.completed_at = utcnow()


def _finish_failure(db, task: GenerationTask, code: str, message: str) -> None:
    if task.status in {TaskStatus.FAILED.value, TaskStatus.REJECTED.value, TaskStatus.CANCELLED.value}:
        return
    release(db, task.user_id, task.frozen_points, "generation", task.id, message)
    task.status = TaskStatus.FAILED.value
    task.error_code = code
    task.error_message = message[:500]
    task.completed_at = utcnow()


@celery_app.task(name="app.workers.tasks.process_generation", bind=True, max_retries=3)
def process_generation(self, task_id: str):
    with SessionLocal() as db:
        task = db.get(GenerationTask, task_id)
        if not task or task.status not in {TaskStatus.QUEUED.value, TaskStatus.PROCESSING.value}:
            return
        task.status = TaskStatus.PROCESSING.value
        db.commit()
        try:
            result = clipcat.submit(task.feature_type, task.prompt, task.request_params)
            task = db.get(GenerationTask, task_id)
            task.provider_task_id = result.provider_task_id
            task.provider_response = result.raw
            if result.status == "succeeded":
                _finish_success(db, task, result.result_urls)
            elif result.status in {"failed", "rejected"}:
                _finish_failure(db, task, "PROVIDER_FAILED", "生成服务返回失败")
            else:
                db.commit()
                poll_generation.apply_async(args=[task_id], countdown=15)
                return
            db.commit()
        except Exception as exc:
            db.rollback()
            task = db.get(GenerationTask, task_id)
            if "PROVIDER_PRICE_CHANGED" in str(exc):
                code = "PRICE_CHANGED"
            elif "PROVIDER_PRICE_POLICY_MISSING" in str(exc):
                code = "PRICE_POLICY_MISSING"
            else:
                code = "PROVIDER_ERROR"
            _finish_failure(db, task, code, str(exc))
            db.commit()


@celery_app.task(name="app.workers.tasks.poll_generation", bind=True, max_retries=40)
def poll_generation(self, task_id: str):
    with SessionLocal() as db:
        task = db.get(GenerationTask, task_id)
        if not task or task.status != TaskStatus.PROCESSING.value or not task.provider_task_id:
            return
        try:
            result = clipcat.query(task.provider_task_id, task.feature_type,
                                   task.request_params.get("provider_task_type"))
            task.provider_response = result.raw
            if result.status == "succeeded":
                _finish_success(db, task, result.result_urls)
                db.commit()
            elif result.status in {"failed", "rejected"}:
                _finish_failure(db, task, "PROVIDER_FAILED", "生成服务返回失败")
                db.commit()
            else:
                db.commit()
                raise self.retry(countdown=min(15 * (self.request.retries + 1), 120))
        except self.MaxRetriesExceededError:
            _finish_failure(db, task, "PROVIDER_TIMEOUT", "生成任务超时")
            db.commit()


@celery_app.task(name="app.workers.tasks.reconcile_stale_tasks")
def reconcile_stale_tasks():
    cutoff = utcnow() - timedelta(hours=2)
    with SessionLocal() as db:
        tasks = db.scalars(select(GenerationTask).where(
            GenerationTask.status.in_([TaskStatus.QUEUED.value, TaskStatus.PROCESSING.value]),
            GenerationTask.updated_at < cutoff,
        )).all()
        for task in tasks:
            _finish_failure(db, task, "STALE_TASK", "任务超时，积分已退还")
        db.commit()


YOGA_PRODUCTS_SETTING_KEY = "hot_products:yoga_pants:US"


@celery_app.task(name="app.workers.tasks.refresh_yoga_products", bind=True, max_retries=3)
def refresh_yoga_products(self, force: bool = False):
    timezone = ZoneInfo(settings.hot_products_timezone)
    refresh_date = datetime.now(timezone).date().isoformat()
    with SessionLocal() as db:
        current = db.get(SystemSetting, YOGA_PRODUCTS_SETTING_KEY)
        if not force and current and current.value.get("refresh_date") == refresh_date:
            return {"status": "skipped", "refresh_date": refresh_date}
    try:
        payload = clipcat.yoga_products(settings.hot_products_region)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=min(60 * (self.request.retries + 1), 300))
    payload.update({
        "refresh_date": refresh_date,
        "refreshed_at": utcnow().isoformat(),
        "schedule": f"每天 00:00（{settings.hot_products_timezone}）",
    })
    with SessionLocal() as db:
        row = db.get(SystemSetting, YOGA_PRODUCTS_SETTING_KEY)
        if row:
            row.value = payload
        else:
            db.add(SystemSetting(key=YOGA_PRODUCTS_SETTING_KEY, value=payload))
        db.commit()
    return {"status": "updated", "refresh_date": refresh_date, "count": len(payload["products"])}
