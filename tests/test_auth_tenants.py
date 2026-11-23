from sqlalchemy import select
from app.database import get_db
from app.models import AuthSession

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
