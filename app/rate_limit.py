"""Shared, database-backed API rate limiting.

Bucket identities are HMAC-pseudonymized before persistence. Fixed windows are
intentionally simple and can permit a two-window boundary burst; see the Phase 2
operations documentation before using this limiter for public production traffic.
"""
from __future__ import annotations

import hmac
import ipaddress
from hashlib import sha256
from math import ceil
import os
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


def _policy(name: str, default_limit: int, default_window: int) -> tuple[int, int]:
    """Load and validate an action policy before the application serves requests."""
    limit_name = f"RATE_LIMIT_{name.upper()}_LIMIT"
    window_name = f"RATE_LIMIT_{name.upper()}_WINDOW_SECONDS"
    try:
        limit = int(os.environ.get(limit_name, default_limit))
        window = int(os.environ.get(window_name, default_window))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{limit_name} and {window_name} must be integers") from exc
    if not 1 <= limit <= 1_000_000:
        raise RuntimeError(f"{limit_name} must be between 1 and 1000000")
    if not 1 <= window <= 31_536_000:
        raise RuntimeError(f"{window_name} must be between 1 and 31536000")
    return limit, window


# Login has a generous shared-IP budget for NAT fairness and a stricter
# per-account budget to constrain distributed password spraying.
POLICIES: dict[str, tuple[int, int]] = {
    "register": _policy("register", 5, 3600),
    "login": _policy("login", 60, 900),
    "login_account": _policy("login_account", 10, 900),
    "login_network": _policy("login_network", 100, 900),
    "member_create": _policy("member_create", 10, 3600),
    "payment_create": _policy("payment_create", 20, 60),
    "refund": _policy("refund", 5, 60),
    "read": _policy("read", 120, 60),
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
    current = int(time()) if now is None else int(now)
    incoming_window = (current // window_seconds) * window_seconds
    bucket_key = _bucket_digest(action, identity)
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        insert_statement = sqlite_insert(RateLimitBucket)
    elif dialect == "postgresql":
        insert_statement = pg_insert(RateLimitBucket)
    else:
        raise RuntimeError("Rate limiting requires SQLite or PostgreSQL atomic upsert support")

    # A delayed request must never move the persisted window backwards. If its
    # sampled window is stale, count it conservatively against the newest window.
    incoming_is_newer = RateLimitBucket.window_start < incoming_window
    statement = insert_statement.values(
        bucket_key=bucket_key,
        window_start=incoming_window,
        request_count=1,
        expires_at=incoming_window + (window_seconds * 2),
    ).on_conflict_do_update(
        index_elements=[RateLimitBucket.bucket_key],
        set_={
            "window_start": case(
                (incoming_is_newer, incoming_window),
                else_=RateLimitBucket.window_start,
            ),
            "request_count": case(
                (incoming_is_newer, 1),
                else_=RateLimitBucket.request_count + 1,
            ),
            "expires_at": case(
                (incoming_is_newer, incoming_window + (window_seconds * 2)),
                else_=RateLimitBucket.expires_at,
            ),
        },
    ).returning(RateLimitBucket.request_count, RateLimitBucket.window_start)

    try:
        request_count, effective_window = db.execute(statement).one()
        # Commit independently before the business handler executes.
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    retry_after = min(window_seconds, max(1, ceil(effective_window + window_seconds - current)))
    return request_count <= limit, retry_after


def _enforce(db: Session, action: str, identity: str) -> None:
    try:
        allowed, retry_after = consume_rate_limit(db, action, identity)
    except (SQLAlchemyError, RuntimeError):
        raise HTTPException(503, "Rate limiting service unavailable", headers={"Retry-After": "5"})
    if not allowed:
        raise HTTPException(
            429,
            "Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def enforce_rate_limit(db: Session, action: str, identity: str) -> None:
    """Enforce an additional server-derived identity bucket inside a route."""
    _enforce(db, action, identity)


def login_network_identity(peer_host: str) -> str:
    """Group login traffic by IPv4 /24 or IPv6 /64 to slow subnet-rotating sprays."""
    try:
        address = ipaddress.ip_address(peer_host)
    except ValueError:
        return f"peer:{peer_host}"
    prefix = 24 if address.version == 4 else 64
    network = ipaddress.ip_network((address, prefix), strict=False)
    return f"network:{network}"


def rate_limit_ip(action: str):
    """Rate-limit public endpoints by the resolved socket peer address."""
    def dependency(request: Request, db: Session = Depends(get_db)) -> None:
        peer = request.client
        if peer is None or not peer.host:
            raise HTTPException(503, "Client network identity unavailable", headers={"Retry-After": "5"})
        _enforce(db, action, f"ip:{peer.host}")
    return dependency


def rate_limit_user(action: str):
    """Rate-limit protected endpoints by verified tenant and user IDs."""
    def dependency(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> None:
        _enforce(db, action, f"tenant:{user.tenant_id}:user:{user.id}")
    return dependency


def purge_expired_rate_limit_buckets(
    db: Session, *, now: int | None = None, batch_size: int = 1000
) -> int:
    """Delete expired buckets in bounded, independently committed batches."""
    if not 1 <= batch_size <= 10_000:
        raise ValueError("batch_size must be between 1 and 10000")
    current = int(time()) if now is None else int(now)
    total_deleted = 0
    try:
        while True:
            expired_keys = (
                select(RateLimitBucket.bucket_key)
                .where(RateLimitBucket.expires_at <= current)
                .order_by(RateLimitBucket.expires_at)
                .limit(batch_size)
            )
            result = db.execute(
                delete(RateLimitBucket).where(
                    RateLimitBucket.expires_at <= current,
                    RateLimitBucket.bucket_key.in_(expired_keys),
                )
            )
            deleted = result.rowcount or 0
            db.commit()
            total_deleted += deleted
            if deleted < batch_size:
                return total_deleted
    except SQLAlchemyError:
        db.rollback()
        raise
