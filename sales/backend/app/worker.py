from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level)

celery_app = Celery("lead_intelligence", broker=settings.redis_url, backend=settings.redis_url,
                    include=["app.tasks.maintenance", "app.tasks.discovery"])
celery_app.conf.update(
    worker_hijack_root_logger=False,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=60 * 60,
    broker_connection_retry_on_startup=True,
    timezone="Asia/Kuala_Lumpur",
    beat_schedule={
        "purge-expired-provider-cache": {
            "task": "maintenance.purge_expired_cache",
            "schedule": crontab(hour=3, minute=15),
        },
        "daily-retention": {"task": "maintenance.retention", "schedule": crontab(hour=3, minute=45)},
        "weekly-saved-search-discovery": {"task": "schedule.weekly_discovery", "schedule": crontab(day_of_week=1, hour=2, minute=0)},
        "monthly-refresh-high-priority": {"task": "schedule.monthly_refresh", "schedule": crontab(day_of_month=1, hour=3, minute=0)},
        "reverify-stale-emails": {"task": "schedule.reverify_emails", "schedule": crontab(day_of_week=3, hour=4, minute=0)},
    },
)
app = celery_app
