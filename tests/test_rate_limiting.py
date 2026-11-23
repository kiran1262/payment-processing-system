from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import Base, enable_sqlite_foreign_keys
from app.models import RateLimitBucket
from app.rate_limit import POLICIES, consume_rate_limit, purge_expired_rate_limit_buckets


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
    second = client.post("/api/auth/login", json=credentials, headers={"X-Forwarded-For": "203.0.113.99"})
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
