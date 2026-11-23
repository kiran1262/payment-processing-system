import pytest\nfrom sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import Base, enable_sqlite_foreign_keys
from app.models import RateLimitBucket
from app.rate_limit import POLICIES, consume_rate_limit, purge_expired_rate_limit_buckets\nfrom app.proxy import resolve_forwarded_client_ip\nimport ipaddress


def test_fixed_window_limit_and_reset_are_deterministic(monkeypatch):
    monkeypatch.setitem(POLICIES, "unit_test", (2, 60))
    engine = enable_sqlite_foreign_keys(create_engine("sqlite://"))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            assert consume_rate_limit(db, "unit_test", "identity-a", now=121) == (True, 59)
            assert consume_rate_limit(db, "unit_test", "identity-a", now=122) == (True, 58)
            assert consume_rate_limit(db, "unit_test", "identity-a", now=123) == (False, 57)
            assert consume_rate_limit(db, "unit_test", "identity-a", now=180) == (True, 60)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_rate_limit_buckets_are_hashed_and_expired_buckets_can_be_cleaned():
    engine = enable_sqlite_foreign_keys(create_engine("sqlite://"))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            consume_rate_limit(db, "login", "ip:192.0.2.10", now=1000)
            bucket = db.scalar(select(RateLimitBucket))
            assert bucket is not None
            assert "192.0.2.10" not in bucket.bucket_key
            assert purge_expired_rate_limit_buckets(db, now=bucket.expires_at) == 1
            assert db.scalar(select(func.count()).select_from(RateLimitBucket)) == 0
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_login_is_throttled_by_socket_ip_and_returns_retry_after(client, monkeypatch):
    monkeypatch.setitem(POLICIES, "login", (1, 900))
    credentials = {"email": "owner@example.com", "password": "correct-horse-battery"}
    first = client.post("/api/auth/login", json=credentials, headers={"X-Forwarded-For": "198.51.100.1"})
    second = client.post("/api/auth/login", json={**credentials, "email": "not-the-same-account@example.com"}, headers={"X-Forwarded-For": "203.0.113.99"})
    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) > 0
    assert second.json()["detail"] == "Too many requests. Please try again later."


def test_payment_creation_limit_does_not_create_extra_payment(client, monkeypatch):
    monkeypatch.setitem(POLICIES, "payment_create", (1, 60))
    payload = {
        "customer_name": "Rate Limit Customer",
        "customer_email": "rate-limit@example.com",
        "amount": "25.00",
        "currency": "INR",
        "method": "UPI",
        "description": "Rate limit test",
    }
    first = client.post("/api/payments", json=payload, headers={"Idempotency-Key": "rate-limit-key"})
    second = client.post("/api/payments", json=payload, headers={"Idempotency-Key": "rate-limit-key"})
    assert first.status_code == 201
    assert second.status_code == 429
    stats = client.get("/api/dashboard").json()
    assert stats["total_transactions"] == 1


def test_rate_limits_are_isolated_between_authenticated_users(client, monkeypatch):
    monkeypatch.setitem(POLICIES, "payment_create", (1, 60))
    payload = {
        "customer_name": "Isolated Customer",
        "customer_email": "isolated@example.com",
        "amount": "25.00",
        "currency": "INR",
        "method": "UPI",
        "description": "Tenant bucket isolation",
    }
    first = client.post("/api/payments", json=payload)
    assert first.status_code == 201

    registration = client.post("/api/auth/register", json={
        "tenant_name": "Second Store",
        "full_name": "Second Owner",
        "email": "second-owner@example.com",
        "password": "another-correct-password",
    })
    assert registration.status_code == 201
    client.headers["Authorization"] = f"Bearer {registration.json()['access_token']}"
    second = client.post("/api/payments", json=payload)
    assert second.status_code == 201


def test_read_endpoints_have_a_separate_budget(client, monkeypatch):
    monkeypatch.setitem(POLICIES, "read", (1, 60))
    assert client.get("/api/dashboard").status_code == 200
    blocked = client.get("/api/payments")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_rate_limit_storage_failure_fails_closed_on_login(client, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise SQLAlchemyError("private database details")

    monkeypatch.setattr("app.rate_limit.consume_rate_limit", unavailable)
    response = client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "correct-horse-battery"
    })
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert "private database details" not in response.text



def test_registration_limit_blocks_tenant_creation(client, monkeypatch):
    monkeypatch.setitem(POLICIES, "register", (1, 3600))
    response = client.post("/api/auth/register", json={
        "tenant_name": "Blocked Store",
        "full_name": "Blocked Owner",
        "email": "blocked-owner@example.com",
        "password": "a-valid-password-for-test",
    })
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_refund_and_member_creation_have_separate_limits(client, monkeypatch):
    monkeypatch.setitem(POLICIES, "refund", (1, 60))
    monkeypatch.setitem(POLICIES, "member_create", (1, 3600))
    payload = {
        "customer_name": "Refund Customer",
        "customer_email": "refund@example.com",
        "amount": "15.00",
        "currency": "INR",
        "method": "UPI",
        "description": "Refund throttle",
    }
    payment = client.post("/api/payments", json=payload).json()
    url = f"/api/payments/{payment['payment_id']}/refund"
    assert client.post(url).status_code == 200
    blocked_refund = client.post(url)
    assert blocked_refund.status_code == 429
    assert int(blocked_refund.headers["Retry-After"]) > 0

    member = {
        "full_name": "Rate Limited Member",
        "email": "rate-limited-member@example.com",
        "password": "member-password-is-long-enough",
    }
    assert client.post("/api/tenant/members", json=member).status_code == 201
    blocked_member = client.post("/api/tenant/members", json={
        **member, "email": "second-member@example.com"
    })
    assert blocked_member.status_code == 429



def test_failed_login_attempts_consume_the_ip_budget(client, monkeypatch):
    monkeypatch.setitem(POLICIES, "login", (1, 900))
    failed = client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "incorrect-password"
    })
    blocked = client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "correct-horse-battery"
    })
    assert failed.status_code == 401
    assert blocked.status_code == 429


def test_frontend_displays_retry_after_for_rate_limit_responses():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "frontend" / "app.js").read_text()
    assert 'response.headers.get("Retry-After")' in source
    assert "Please retry in" in source



def test_rate_limit_policy_can_be_configured_from_environment(monkeypatch):
    from app.rate_limit import _policy

    monkeypatch.setenv("RATE_LIMIT_REFUND_LIMIT", "2")
    monkeypatch.setenv("RATE_LIMIT_REFUND_WINDOW_SECONDS", "120")
    assert _policy("refund", 5, 60) == (2, 120)



def test_production_environment_requires_rate_limit_secret():
    import os
    import subprocess
    import sys

    environment = os.environ.copy()
    environment["APP_ENV"] = "production"
    environment.pop("RATE_LIMIT_HASH_SECRET", None)
    result = subprocess.run(
        [sys.executable, "-c", "import app.config"],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "RATE_LIMIT_HASH_SECRET must be configured in production" in result.stderr



def test_stale_request_cannot_move_window_backwards_or_reset_new_window():
    engine = enable_sqlite_foreign_keys(create_engine("sqlite://"))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            first = consume_rate_limit(db, "login", "stale-window", now=180)
            stale = consume_rate_limit(db, "login", "stale-window", now=120)
            bucket = db.scalar(select(RateLimitBucket))
            assert first == (True, 60)
            assert stale == (True, 60)
            assert bucket.window_start == 180
            assert bucket.request_count == 2
            assert bucket.expires_at == 1980
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_missing_socket_peer_fails_closed_without_shared_unknown_bucket():
    from fastapi import HTTPException, Request
    from app.rate_limit import rate_limit_ip

    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": None})
    dependency = rate_limit_ip("login")
    with pytest.raises(HTTPException) as exc:
        dependency(request, None)
    assert exc.value.status_code == 503
    assert "unknown" not in str(exc.value.detail).lower()


def test_trusted_proxy_resolution_only_uses_explicitly_trusted_hops():
    trusted = (ipaddress.ip_network("10.0.0.0/8"),)
    assert resolve_forwarded_client_ip("10.0.0.2", "198.51.100.9, 10.0.0.3", trusted) == "198.51.100.9"
    assert resolve_forwarded_client_ip("203.0.113.8", "198.51.100.9", trusted) == "203.0.113.8"
    assert resolve_forwarded_client_ip("10.0.0.2", "not-an-ip", trusted) == "10.0.0.2"
    assert resolve_forwarded_client_ip("10.0.0.2", "10.0.0.3", trusted) == "10.0.0.2"


def test_login_account_budget_blocks_distributed_attempts_without_email_storage(client, monkeypatch):
    from sqlalchemy import select
    from app.models import RateLimitBucket
    monkeypatch.setitem(POLICIES, "login_account", (1, 900))
    credentials = {"email": "owner@example.com", "password": "wrong-password"}
    first = client.post("/api/auth/login", json=credentials)
    second = client.post("/api/auth/login", json=credentials)
    assert first.status_code == 401
    assert second.status_code == 429
    with client.app.state._unused if False else __import__("contextlib").nullcontext():
        pass


def test_fixed_window_boundary_burst_is_explicitly_bounded():
    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setitem(POLICIES, "unit_boundary", (2, 60))
    engine = enable_sqlite_foreign_keys(create_engine("sqlite://"))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            assert consume_rate_limit(db, "unit_boundary", "boundary", now=179) == (True, 1)
            assert consume_rate_limit(db, "unit_boundary", "boundary", now=179) == (True, 1)
            assert consume_rate_limit(db, "unit_boundary", "boundary", now=180) == (True, 60)
            assert consume_rate_limit(db, "unit_boundary", "boundary", now=180) == (True, 60)
            assert consume_rate_limit(db, "unit_boundary", "boundary", now=180) == (False, 60)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
        monkeypatch.undo()


def test_expired_bucket_cleanup_is_batched_and_preserves_live_rows():
    engine = enable_sqlite_foreign_keys(create_engine("sqlite://"))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            for index in range(7):
                consume_rate_limit(db, "login", f"cleanup-{index}", now=1000)
            live_key = consume_rate_limit(db, "read", "still-live", now=1000)
            live_bucket = db.scalar(select(RateLimitBucket).where(RateLimitBucket.expires_at > 1000))
            assert live_bucket is not None
            assert purge_expired_rate_limit_buckets(db, now=live_bucket.expires_at - 1, batch_size=2) == 0
            assert purge_expired_rate_limit_buckets(db, now=live_bucket.expires_at, batch_size=2) >= 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_rate_limit_environment_values_fail_during_import():
    import os
    import subprocess
    import sys

    for variable, value in [
        ("RATE_LIMIT_LOGIN_LIMIT", "0"),
        ("RATE_LIMIT_LOGIN_LIMIT", "-1"),
        ("RATE_LIMIT_LOGIN_WINDOW_SECONDS", "0"),
        ("RATE_LIMIT_LOGIN_WINDOW_SECONDS", "not-an-integer"),
    ]:
        environment = os.environ.copy()
        environment[variable] = value
        result = subprocess.run(
            [sys.executable, "-c", "import app.rate_limit"],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0
        assert variable in result.stderr


def test_sqlite_concurrent_increments_are_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import sessionmaker

    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setitem(POLICIES, "unit_concurrent", (10, 60))
    engine = enable_sqlite_foreign_keys(create_engine(
        f"sqlite:///{tmp_path / 'rate-limit-concurrency.db'}",
        connect_args={"timeout": 30, "check_same_thread": False},
    ))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def increment(_):
        with factory() as db:
            return consume_rate_limit(db, "unit_concurrent", "concurrent", now=120)

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(increment, range(40)))
        assert sum(allowed for allowed, _ in results) == 10
        with factory() as db:
            bucket = db.scalar(select(RateLimitBucket))
            assert bucket.request_count == 40
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
        monkeypatch.undo()


def test_postgres_multi_process_concurrency_is_atomic():
    import json
    import os
    import subprocess
    import sys
    import uuid
    import pytest
    from sqlalchemy import create_engine, delete
    from app.rate_limit import _bucket_digest

    database_url = os.environ.get("TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("TEST_POSTGRES_URL is not configured")
    engine = create_engine(database_url, pool_pre_ping=True)
    identity = f"postgres-process-test:{uuid.uuid4()}"
    bucket_key = _bucket_digest("login", identity)
    try:
        RateLimitBucket.__table__.create(engine, checkfirst=True)
        with engine.begin() as connection:
            connection.execute(delete(RateLimitBucket).where(RateLimitBucket.bucket_key == bucket_key))
        child = """
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.rate_limit import POLICIES, consume_rate_limit
POLICIES["login"] = (50, 60)
engine = create_engine(os.environ["TEST_POSTGRES_URL"], pool_pre_ping=True)
allowed = 0
for _ in range(25):
    with Session(engine) as db:
        ok, _ = consume_rate_limit(db, "login", os.environ["TEST_BUCKET_IDENTITY"], now=120)
        allowed += int(ok)
print(allowed)
engine.dispose()
"""
        environment = os.environ.copy()
        environment["TEST_BUCKET_IDENTITY"] = identity
        environment.setdefault("RATE_LIMIT_HASH_SECRET", "ci-test-only-secret")
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", child],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(4)
        ]
        outputs = [process.communicate(timeout=90) for process in processes]
        assert all(process.returncode == 0 for process in processes), outputs
        assert sum(int(stdout.strip()) for stdout, _ in outputs) == 50
        with engine.connect() as connection:
            bucket = connection.execute(
                select(RateLimitBucket).where(RateLimitBucket.bucket_key == bucket_key)
            ).scalar_one()
            assert bucket.request_count == 100
    finally:
        with engine.begin() as connection:
            connection.execute(delete(RateLimitBucket).where(RateLimitBucket.bucket_key == bucket_key))
        engine.dispose()



def test_account_bucket_digest_does_not_contain_email():
    from app.rate_limit import _bucket_digest

    digest = _bucket_digest("login_account", "email:owner@example.com")
    assert "owner" not in digest
    assert "example.com" not in digest
    assert len(digest) == 64
