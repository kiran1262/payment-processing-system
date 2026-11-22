def payload(**overrides):
    data = {
        "customer_name": "Alex Morgan",
        "customer_email": "alex@example.com",
        "amount": "1250.50",
        "currency": "INR",
        "method": "UPI",
        "description": "Test order",
    }
    data.update(overrides)
    return data


def test_health(client):
    assert client.get("/api/health").json()["status"] == "healthy"


def test_create_payment_and_dashboard(client):
    response = client.post("/api/payments", json=payload())
    assert response.status_code == 201
    assert response.json()["status"] == "succeeded"
    stats = client.get("/api/dashboard").json()
    assert stats["total_transactions"] == 1
    assert stats["revenue_paise"] == 125050


def test_declined_demo_payment(client):
    response = client.post("/api/payments", json=payload(amount="99.99"))
    assert response.status_code == 201
    assert response.json()["status"] == "declined"


def test_idempotency_replays_identical_request(client):
    headers = {"Idempotency-Key": "order-123"}
    first = client.post("/api/payments", json=payload(), headers=headers)
    second = client.post("/api/payments", json=payload(), headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["payment_id"] == second.json()["payment_id"]
    assert second.json()["idempotent_replay"] is True
    assert client.get("/api/dashboard").json()["total_transactions"] == 1


def test_idempotency_rejects_different_amount(client):
    headers = {"Idempotency-Key": "order-amount-conflict"}
    first = client.post("/api/payments", json=payload(), headers=headers)
    second = client.post("/api/payments", json=payload(amount="2200.00"), headers=headers)
    assert first.status_code == 201
    assert second.status_code == 409


def test_idempotency_rejects_different_customer(client):
    headers = {"Idempotency-Key": "order-customer-conflict"}
    client.post("/api/payments", json=payload(), headers=headers)
    response = client.post(
        "/api/payments", json=payload(customer_name="Jordan Smith"), headers=headers
    )
    assert response.status_code == 409


def test_amount_rejects_more_than_two_decimal_places(client):
    response = client.post("/api/payments", json=payload(amount="10.999"))
    assert response.status_code == 422


def test_amount_rejects_zero_and_negative(client):
    assert client.post("/api/payments", json=payload(amount="0")).status_code == 422
    assert client.post("/api/payments", json=payload(amount="-1")).status_code == 422


def test_invalid_email_is_rejected(client):
    response = client.post("/api/payments", json=payload(customer_email="not-an-email"))
    assert response.status_code == 422


def test_payment_list_rejects_invalid_limits(client):
    assert client.get("/api/payments?limit=0").status_code == 422
    assert client.get("/api/payments?limit=-1").status_code == 422
    assert client.get("/api/payments?limit=251").status_code == 422


def test_refund_successful_payment(client):
    payment = client.post("/api/payments", json=payload()).json()
    response = client.post(f"/api/payments/{payment['payment_id']}/refund")
    assert response.status_code == 200
    assert response.json()["status"] == "refunded"
    assert response.json()["amount"] == 1250.5


def test_refund_is_idempotent(client):
    payment = client.post("/api/payments", json=payload()).json()
    url = f"/api/payments/{payment['payment_id']}/refund"
    first, second = client.post(url), client.post(url)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "refunded"


def test_cannot_refund_declined_payment(client):
    payment = client.post("/api/payments", json=payload(amount="99.99")).json()
    response = client.post(f"/api/payments/{payment['payment_id']}/refund")
    assert response.status_code == 409


def test_dashboard_metrics_are_consistent_after_refund(client):
    payment = client.post("/api/payments", json=payload()).json()
    client.post(f"/api/payments/{payment['payment_id']}/refund")
    stats = client.get("/api/dashboard").json()
    assert stats["successful"] == 0
    assert stats["refunded"] == 1
    assert stats["success_rate"] == 100.0
    assert stats["revenue_paise"] == 0
