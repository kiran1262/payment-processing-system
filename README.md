# Payment Processing System

A full-stack educational payment-processing demo with a neon analytics dashboard, FastAPI REST API, SQLAlchemy persistence, simulated payments, idempotency, refunds, and automated tests.

## Important safety and deployment notice

This project is a **simulation**. It does not connect to a bank, card network, UPI provider, or Stripe and it never moves real money. Do not enter real card numbers, CVVs, UPI PINs, or banking credentials. A successful demo response is not a real payment authorization.

The application is intended for local learning. It is **not production-ready**: it currently has no user authentication/authorization, API rate limiting, tenant isolation, audit trail, production-grade ledger/reconciliation, signed provider webhooks, or secrets-management integration. Do not expose it to the public internet or use it to process real payments. A browser-delivered API key is not a safe substitute for server-side user authentication.

## Features

- Responsive dark navy / neon dashboard
- Create simulated payments using Card, UPI, Wallet, or Net Banking labels
- Transaction history and SQL-aggregated dashboard metrics
- Payment detail endpoint and simulated refunds
- Idempotency-Key support with request-payload conflict detection
- Exact decimal-to-paise conversion and email validation
- Bounded payment listing and database-safe refund state transition
- SQLite database created automatically for the local demo
- FastAPI interactive API documentation at /docs
- Pytest suite for payment, validation, idempotency, and refund flows

## Architecture

    Browser (HTML / CSS / JavaScript)
              |
              | HTTP / JSON
              v
    FastAPI application
      |-- REST endpoints
      |-- Payment service
      |-- Idempotency handling
      |-- Conditional refund state transition
      |-- SQL aggregate dashboard queries
              |
              v
    SQLAlchemy ORM ---- SQLite (payment.db)

## Requirements

- Python 3.11+
- Windows PowerShell (commands below) or macOS/Linux

## Run on Windows PowerShell

    py -3.11 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    python -m uvicorn app.main:app --reload

Open http://127.0.0.1:8000 for the dashboard and http://127.0.0.1:8000/docs for API docs.

## Run tests

    python -m pytest -v

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /api/health | Health check |
| GET | /api/dashboard | Dashboard metrics |
| GET | /api/payments | List recent payments |
| POST | /api/payments | Create a simulated payment |
| GET | /api/payments/{payment_id} | Retrieve a payment |
| POST | /api/payments/{payment_id}/refund | Refund a successful demo payment |

### Create payment example

    $body = @{
      customer_name = "Alex Morgan"
      customer_email = "alex@example.com"
      amount = "1499.00"
      currency = "INR"
      method = "UPI"
      description = "Order #1001"
    } | ConvertTo-Json

    Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/payments -ContentType "application/json" -Headers @{"Idempotency-Key"="demo-order-1001"} -Body $body

Reusing an idempotency key with the same request returns the original payment. Reusing it with different payment details returns **409 Conflict**. Keys must be between 1 and 100 characters.

### Demo decline scenario

For learning purposes only, amounts ending in .99 are declined. For example, 99.99 produces a declined status. Other valid amounts are simulated as successful. This is not a real issuer or fraud decision.

## Dashboard metric definitions

- **Successful** counts payments currently in the succeeded state.
- **Refunded** counts payments transitioned to refunded.
- **Revenue** sums only payments still in the succeeded state; refunded payments are excluded.
- **Success rate** counts succeeded plus refunded payments as successful payment outcomes, divided by all transactions.

## Production engineering still required

Before any real payment integration or public deployment:

- Integrate an authorized payment service provider using its official SDK and sandbox.
- Add server-side authentication, authorization, tenant isolation, and API rate limiting.
- Verify signed provider webhooks and make webhook processing idempotent.
- Introduce Alembic migrations and a production database such as PostgreSQL.
- Implement a proper double-entry ledger, reconciliation, audit logs, and monitoring.
- Add secrets management, TLS, secure deployment configuration, and security review.
- Never store raw card data or CVV; follow the provider's current compliance requirements.

Do not make the demo publicly accessible until the above controls are implemented and reviewed.

## Project structure

    payment-processing-system/
    ├── app/
    │   ├── __init__.py
    │   ├── config.py
    │   ├── database.py
    │   ├── main.py
    │   ├── models.py
    │   ├── schemas.py
    │   └── services.py
    ├── frontend/
    │   ├── index.html
    │   ├── styles.css
    │   └── app.js
    ├── tests/
    │   ├── conftest.py
    │   └── test_payments.py
    ├── .gitignore
    ├── README.md
    └── requirements.txt
