from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError
from app.database import get_db
from app.main import app

def register(client, tenant, name, email):
    response = client.post("/api/auth/register", json={
        "tenant_name": tenant, "full_name": name, "email": email,
        "password": "another-secure-password",
    })
    assert response.status_code == 201
    return response.json()

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def payment_payload(**changes):
    data = {"customer_name": "Taylor Reed", "customer_email": "taylor@example.com",
            "amount": "45.00", "currency": "INR", "method": "UPI", "description": "Tenant test"}
    data.update(changes)
    return data

def test_protected_payment_routes_require_authentication(client):
    assert client.get("/api/payments", headers={"Authorization": ""}).status_code == 401
    assert client.get("/api/dashboard", headers={"Authorization": ""}).status_code == 401
    assert client.post("/api/payments", json=payment_payload(), headers={"Authorization": ""}).status_code == 401

def test_login_and_logout_revoke_session(client):
    client.headers.pop("Authorization")
    bad = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "wrong-password"})
    assert bad.status_code == 401
    good = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "correct-horse-battery"})
    assert good.status_code == 200
    token = good.json()["access_token"]
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 200
    assert client.post("/api/auth/logout", headers=auth(token)).status_code == 204
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 401

def test_duplicate_registration_is_rejected(client):
    response = client.post("/api/auth/register", json={
        "tenant_name": "Other Store", "full_name": "Other Owner",
        "email": "owner@example.com", "password": "another-secure-password",
    })
    assert response.status_code == 409

def test_tenant_cannot_read_or_refund_another_tenants_payment(client):
    first = client.post("/api/payments", json=payment_payload())
    assert first.status_code == 201
    payment_id = first.json()["payment_id"]
    second = register(client, "Second Store", "Second Owner", "second@example.com")
    headers = auth(second["access_token"])
    assert client.get("/api/payments", headers=headers).json() == []
    assert client.get("/api/dashboard", headers=headers).json()["total_transactions"] == 0
    assert client.get(f"/api/payments/{payment_id}", headers=headers).status_code == 404
    assert client.post(f"/api/payments/{payment_id}/refund", headers=headers).status_code == 404

def test_idempotency_key_is_scoped_to_tenant(client):
    headers = {"Idempotency-Key": "same-key"}
    first = client.post("/api/payments", json=payment_payload(), headers=headers)
    second_owner = register(client, "Independent Store", "Independent Owner", "independent@example.com")
    other = client.post("/api/payments", json=payment_payload(), headers={**auth(second_owner["access_token"]), **headers})
    assert first.status_code == other.status_code == 201
    assert first.json()["payment_id"] != other.json()["payment_id"]
    replay = client.post("/api/payments", json=payment_payload(), headers=headers)
    assert replay.json()["payment_id"] == first.json()["payment_id"]
    assert replay.json()["idempotent_replay"] is True

def test_member_cannot_refund_or_create_members(client):
    member = client.post("/api/tenant/members", json={
        "full_name": "Store Member", "email": "member@example.com",
        "password": "member-secure-password",
    })
    assert member.status_code == 201
    payment = client.post("/api/payments", json=payment_payload()).json()
    login = client.post("/api/auth/login", json={
        "email": "member@example.com", "password": "member-secure-password",
    }).json()
    headers = auth(login["access_token"])
    assert client.post(f"/api/payments/{payment['payment_id']}/refund", headers=headers).status_code == 403
    assert client.post("/api/tenant/members", headers=headers, json={
        "full_name": "Another Member", "email": "another@example.com",
        "password": "another-member-password",
    }).status_code == 403

def test_registration_never_accepts_client_selected_tenant_id(client):
    first = client.get("/api/auth/me").json()
    response = client.post("/api/payments", json={**payment_payload(), "tenant_id": 999999})
    assert response.status_code == 201
    assert client.get("/api/auth/me").json()["tenant_id"] == first["tenant_id"]

def test_readiness_endpoint(client):
    assert client.get("/api/ready").json() == {"status": "ready", "database": "available"}

def test_payment_detail_and_refund_also_require_authentication(client):
    assert client.get("/api/payments/pay_unknown", headers={"Authorization": ""}).status_code == 401
    assert client.post("/api/payments/pay_unknown/refund", headers={"Authorization": ""}).status_code == 401

def test_readiness_returns_generic_503_when_database_is_unavailable(client):
    previous_override = app.dependency_overrides[get_db]

    class BrokenDatabase:
        def execute(self, statement):
            raise SQLAlchemyError("sensitive connection string must not be returned")
        def close(self):
            pass

    def broken_db():
        yield BrokenDatabase()

    app.dependency_overrides[get_db] = broken_db
    try:
        response = client.get("/api/ready")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database unavailable"}
        assert "sensitive" not in response.text
    finally:
        app.dependency_overrides[get_db] = previous_override

def test_frontend_reuses_idempotency_key_for_same_retry_payload():
    source = (Path(__file__).resolve().parents[1] / "frontend" / "app.js").read_text()
    assert 'sessionStorage.getItem("pending_payment_key")' in source
    assert 'sessionStorage.setItem("pending_payment_key",key)' in source
    assert "previousFingerprint!==requestFingerprint" in source
    assert 'sessionStorage.removeItem("pending_payment_key")' in source

def test_expired_bearer_session_is_rejected(client):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.auth import token_digest
    from app.models import AuthSession

    token = client.headers["Authorization"].split(" ", 1)[1]
    dependency = app.dependency_overrides[get_db]
    generator = dependency()
    db = next(generator)
    try:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(token)))
        session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        generator.close()
    assert client.get("/api/auth/me").status_code == 401

def test_frontend_avoids_unsubstantiated_security_claims():
    source = (Path(__file__).resolve().parents[1] / "frontend" / "index.html").read_text()
    lowered = source.lower()
    assert "move money with confidence" not in lowered
    assert "secure payment" not in lowered
    assert "encrypted demo request" not in lowered
    assert "all systems operational" not in lowered
    assert "illustrative activity" in lowered
    assert "no real payments" in lowered



def test_sqlite_foreign_key_constraints_are_enforced():
    from sqlalchemy import create_engine
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session
    from app.database import Base, enable_sqlite_foreign_keys
    from app.models import User

    engine = enable_sqlite_foreign_keys(create_engine("sqlite://"))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(User(
                tenant_id=987654,
                full_name="Orphan User",
                email="orphan@example.com",
                password_hash="not-a-real-hash",
                role="member",
            ))
            try:
                db.commit()
                assert False, "SQLite accepted a user with a missing tenant"
            except IntegrityError:
                db.rollback()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_legacy_workspace_owner_bootstrap_is_local_and_one_time():
    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.auth import bootstrap_legacy_owner, verify_password
    from app.database import Base, enable_sqlite_foreign_keys
    from app.models import Tenant

    engine = enable_sqlite_foreign_keys(create_engine("sqlite://"))
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(Tenant(id=1, name="Legacy demo workspace"))
            db.commit()
            owner = bootstrap_legacy_owner(
                db, "Legacy Owner", "legacy-owner@example.com", "legacy-owner-password"
            )
            assert owner.tenant_id == 1
            assert owner.role == "owner"
            assert verify_password("legacy-owner-password", owner.password_hash)
            with pytest.raises(ValueError, match="one-time only"):
                bootstrap_legacy_owner(
                    db, "Second Owner", "second-legacy@example.com", "another-password"
                )
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_frontend_refund_action_is_owner_only_and_sidebar_uses_profile_data():
    root = Path(__file__).resolve().parents[1]
    js = (root / "frontend" / "app.js").read_text()
    html = (root / "frontend" / "index.html").read_text()
    assert 'currentUser?.role==="owner" && p.status==="succeeded"' in js
    assert 'el("workspaceName").textContent = workspaceName' in js
    assert 'el("profileName").textContent = user.full_name' in js
    assert 'id="workspaceName"' in html
    assert 'id="profileRole"' in html
    assert "Kirankumar" not in html



def test_authenticated_profile_includes_dynamic_workspace_identity(client):
    profile = client.get("/api/auth/me").json()
    assert profile["tenant_name"] == "Test Store"
    assert profile["full_name"] == "Test Owner"
    assert profile["role"] == "owner"
