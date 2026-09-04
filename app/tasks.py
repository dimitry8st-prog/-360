from celery import Celery

from app.config import settings

celery_app = Celery("dis360", broker=settings().redis_url, backend=settings().redis_url)
celery_app.conf.update(task_track_started=True, task_time_limit=300, task_soft_time_limit=270)


@celery_app.task
def health_task() -> str:
    return "ok"

