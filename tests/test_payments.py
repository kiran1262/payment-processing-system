def payload(**overrides):
    data={"customer_name":"Alex Morgan","customer_email":"alex@example.com","amount":1250.50,"currency":"INR","method":"UPI","description":"Test order"}
    data.update(overrides)
    return data

def test_health(client):
    assert client.get("/api/health").json()["status"] == "healthy"

def test_create_payment_and_dashboard(client):
    response=client.post("/api/payments",json=payload())
    assert response.status_code == 201
    assert response.json()["status"] == "succeeded"
    stats=client.get("/api/dashboard").json()
    assert stats["total_transactions"] == 1
    assert stats["revenue_paise"] == 125050

def test_declined_demo_payment(client):
    response=client.post("/api/payments",json=payload(amount=99.99))
    assert response.status_code == 201
    assert response.json()["status"] == "declined"

def test_idempotency_key_replays_existing_payment(client):
    headers={"Idempotency-Key":"order-123"}
    first=client.post("/api/payments",json=payload(),headers=headers).json()
    second=client.post("/api/payments",json=payload(amount=2200),headers=headers).json()
    assert first["payment_id"] == second["payment_id"]
    assert second["idempotent_replay"] is True
    assert client.get("/api/dashboard").json()["total_transactions"] == 1

def test_refund_successful_payment(client):
    payment=client.post("/api/payments",json=payload()).json()
    response=client.post(f"/api/payments/{payment['payment_id']}/refund")
    assert response.status_code == 200
    assert response.json()["status"] == "refunded"

def test_cannot_refund_declined_payment(client):
    payment=client.post("/api/payments",json=payload(amount=99.99)).json()
    response=client.post(f"/api/payments/{payment['payment_id']}/refund")
    assert response.status_code == 409
