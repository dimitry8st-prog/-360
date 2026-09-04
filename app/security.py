from __future__ import annotations

import base64
import hashlib
import hmac
import os

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import settings


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt64, digest64 = encoded.split("$", 3)
        salt = base64.b64decode(salt64)
        expected = base64.b64decode(digest64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings().secret_key, salt="dis360-session")


def make_session(user_id: int) -> str:
    return serializer().dumps({"uid": user_id})


def read_session(token: str | None, max_age: int = 60 * 60 * 24 * 7) -> int | None:
    if not token:
        return None
    try:
        return int(serializer().loads(token, max_age=max_age)["uid"])
    except (BadSignature, KeyError, TypeError, ValueError):
        return None

