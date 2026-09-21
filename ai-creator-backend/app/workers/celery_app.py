import sys

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings


celery_app = Celery("ai_creator", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_always_eager=settings.celery_always_eager,
    task_eager_propagates=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.hot_products_timezone,
    # macOS Python 3.8+ uses spawn; Celery's default prefork pool then crashes with
    # "not enough values to unpack (expected 3, got 0)" before ClipCat is called.
    worker_pool="threads" if sys.platform == "darwin" else "prefork",
    beat_schedule={
        "reconcile-stale-tasks": {
            "task": "app.workers.tasks.reconcile_stale_tasks",
            "schedule": 300.0,
        },
        "refresh-yoga-products-at-midnight": {
            "task": "app.workers.tasks.refresh_yoga_products",
            "schedule": crontab(hour=0, minute=0),
        },
    },
)
celery_app.autodiscover_tasks(["app.workers"])
