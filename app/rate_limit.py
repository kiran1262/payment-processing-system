"""Shared, database-backed API rate limiting.

Identity values are hashed before persistence. Forwarded IP headers are deliberately
ignored; configure trusted proxy handling at the deployment edge if required.
"""
from __future__ import annotations

import hmac
from hashlib import sha256
from math import ceil
from time import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import get_current_user
from .config import RATE_LIMIT_HASH_SECRET
from .database import get_db
from .models import RateLimitBucket, User

# limit, window_seconds. Keep policies action-specific and easy to override in tests.
POLICIES: dict[str, tuple[int, int]] = {
    "register": (5, 3600),
    "login": (10, 900),
    "member_create": (10, 3600),
    "payment_create": (20, 60),
    "refund": (5, 60),
    "read": (120, 60),
}


def _bucket_digest(action: str, identity: str) -> str:
    message = f"rate-limit:v1:{action}:{identity}".encode("utf-8")
    return hmac.new(RATE_LIMIT_HASH_SECRET.encode("utf-8"), message, sha256).hexdigest()


def consume_rate_limit(
    db: Session, action: str, identity: str, *, now: int | None = None
) -> tuple[bool, int]:
    """Atomically increment a fixed-window bucket; return (allowed, retry_after)."""
    if action not in POLICIES:
        raise ValueError(f"Unknown rate-limit action: {action}")
    limit, window_seconds = POLICIES[action]
    if limit < 1 or window_seconds < 1:
        raise ValueError("Rate-limit policy values must be positive")

    current = int(time()) if now is None else int(now)
    window_start = (current // window_seconds) * window_seconds
    bucket_key = _bucket_digest(action, identity)
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        insert_statement = sqlite_insert(RateLimitBucket)
    elif dialect == "postgresql":
        insert_statement = pg_insert(RateLimitBucket)
    else:
        raise RuntimeError("Rate limiting requires SQLite or PostgreSQL atomic upsert support")

    statement = insert_statement.values(
        bucket_key=bucket_key,
        window_start=window_start,
        request_count=1,
        expires_at=window_start + (window_seconds * 2),
    ).on_conflict_do_update(
        index_elements=[RateLimitBucket.bucket_key],
        set_={
            "window_start": case(
                (RateLimitBucket.window_start == window_start, RateLimitBucket.window_start),
                else_=window_start,
            ),
            "request_count": case(
                (RateLimitBucket.window_start == window_start, RateLimitBucket.request_count + 1),
                else_=1,
            ),
            "expires_at": window_start + (window_seconds * 2),
        },
    ).returning(RateLimitBucket.request_count)

    try:
        request_count = db.execute(statement).scalar_one()
        # Commit the counter independently before the business handler runs.
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    retry_after = max(1, ceil(window_start + window_seconds - current))
    return request_count <= limit, retry_after


def _enforce(db: Session, action: str, identity: str) -> None:
    try:
        allowed, retry_after = consume_rate_limit(db, action, identity)
    except (SQLAlchemyError, RuntimeError):
        # Fail closed: an unavailable limiter must not silently disable protection.
        raise HTTPException(503, "Rate limiting service unavailable", headers={"Retry-After": "5"})
    if not allowed:
        raise HTTPException(
            429,
            "Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit_ip(action: str):
    """Rate-limit public endpoints by the socket peer address."""
    def dependency(request: Request, db: Session = Depends(get_db)) -> None:
        peer_ip = request.client.host if request.client is not None else "unknown"
        _enforce(db, action, f"ip:{peer_ip}")
    return dependency


def rate_limit_user(action: str):
    """Rate-limit protected endpoints by verified tenant and user IDs."""
    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> None:
        _enforce(db, action, f"tenant:{user.tenant_id}:user:{user.id}")
    return dependency


def purge_expired_rate_limit_buckets(db: Session, *, now: int | None = None) -> int:
    """Delete expired buckets; call from a scheduled maintenance task."""
    current = int(time()) if now is None else int(now)
    result = db.execute(delete(RateLimitBucket).where(RateLimitBucket.expires_at <= current))
    db.commit()
    return result.rowcount or 0
