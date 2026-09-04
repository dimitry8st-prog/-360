from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")
SIZE_RE = re.compile(r"^(\d+)\s*(B|KB|MB|GB)?$", re.I)
UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}


def size_bytes(value: str) -> int:
    match = SIZE_RE.match(value.strip())
    if not match:
        raise ValueError(f"Некорректный размер: {value}")
    return int(match.group(1)) * UNITS[(match.group(2) or "B").upper()]


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    secret_key: str
    database_url: str
    redis_url: str
    max_file_size: str
    max_file_size_bytes: int
    upload_dir: Path
    output_dir: Path
    retention_days: int
    log_level: str
    admin_email: str
    admin_password: str
    openai_api_key: str | None
    openai_model: str
    daily_limit: int
    sandbox_enabled: bool


@lru_cache
def settings() -> Settings:
    max_size = os.getenv("MAX_FILE_SIZE", "20MB")
    return Settings(
        app_name=os.getenv("APP_NAME", "ДИС Аналитик 360"),
        app_env=os.getenv("APP_ENV", "development"),
        secret_key=os.getenv("SECRET_KEY", "dev-only-change-me"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./dis360.db"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        max_file_size=max_size,
        max_file_size_bytes=size_bytes(max_size),
        upload_dir=BASE_DIR / os.getenv("UPLOAD_DIR", "storage/uploads"),
        output_dir=BASE_DIR / os.getenv("OUTPUT_DIR", "storage/outputs"),
        retention_days=int(os.getenv("FILE_RETENTION_DAYS", "30")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        admin_email=os.getenv("ADMIN_EMAIL", "admin@example.com").lower(),
        admin_password=os.getenv("ADMIN_PASSWORD", "change-me-admin-password"),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        daily_limit=int(os.getenv("OPENAI_DAILY_REQUEST_LIMIT", "25")),
        sandbox_enabled=os.getenv("ENABLE_AI_CODE_SANDBOX", "false").lower() == "true",
    )

