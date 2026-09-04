from datetime import UTC, datetime, timedelta

from celery import Celery
from sqlalchemy import select

from app.config import settings
from app.database import FileRecord, SessionLocal

celery_app = Celery("dis360", broker=settings().redis_url, backend=settings().redis_url)
celery_app.conf.update(
    task_track_started=True,
    task_time_limit=300,
    task_soft_time_limit=270,
    beat_schedule={"cleanup-expired-files-daily": {"task": "app.tasks.cleanup_expired_files", "schedule": 86400.0}},
)


@celery_app.task
def health_task() -> str:
    return "ok"


@celery_app.task(name="app.tasks.cleanup_expired_files")
def cleanup_expired_files() -> dict[str, int]:
    cfg = settings()
    cutoff = datetime.now(UTC) - timedelta(days=cfg.retention_days)
    removed = 0
    with SessionLocal() as db:
        records = db.scalars(select(FileRecord).where(FileRecord.created_at < cutoff)).all()
        for record in records:
            (cfg.upload_dir / record.stored_name).unlink(missing_ok=True)
            db.delete(record); removed += 1
        db.commit()
    return {"removed": removed}
