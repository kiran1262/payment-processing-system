# Payment Processing System

A full-stack educational payment-processing demo with a neon analytics dashboard, FastAPI REST API, SQLAlchemy persistence, simulated payments, idempotency, refunds, and automated tests.

## Important safety and deployment notice

This project is a **simulation**. It does not connect to a bank, card network, UPI provider, or Stripe and it never moves real money. Do not enter real card numbers, CVVs, UPI PINs, or banking credentials. A successful demo response is not a real payment authorization.

The application is intended for local learning. It now includes basic application-level authentication, owner/member authorization, and tenant-scoped demo data, but it is **not production-ready**. It still lacks rate limiting, durable audit trails, a production identity/session architecture, a ledger/reconciliation system, signed provider webhooks, and secrets-management integration. Browser bearer tokens are held in session storage for this demo and remain exposed to browser-side compromise such as XSS. Do not expose it to the public internet or use it to process real payments.

## Features

- Responsive dark navy / neon dashboard
- Create simulated payments using Card, UPI, Wallet, or Net Banking labels
- Transaction history and SQL-aggregated dashboard metrics
- Payment detail endpoint and simulated refunds
- Registration, login, logout, expiring bearer sessions, and PBKDF2 password hashing
- Owner/member roles with owner-only refunds and tenant membership management
- Tenant-isolated payment lists, details, refunds, dashboards, and idempotency keys
- Idempotency-Key support with request-payload conflict detection and safe browser retries
- Exact decimal-to-paise conversion and email validation
- Bounded payment listing and database-safe refund state transition
- Explicit Alembic database migrations; application startup does not create or alter tables
- FastAPI interactive API documentation at /docs
- Pytest suite for payment, validation, idempotency, refund, and migration flows

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

The commands below do **not** require virtual-environment activation. This avoids the common PowerShell execution-policy error that can block `Activate.ps1`.

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe -m alembic upgrade head
    .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

If the `py` launcher is not installed but Python 3.11+ is available on your PATH, create the environment with:

    python -m venv .venv

Then run the remaining commands with `.\.venv\Scripts\python.exe` as the Python executable; the path is relative to the project folder.

### Optional: activate the environment

Activation is optional. If you prefer it, run:

    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
    .\.venv\Scripts\Activate.ps1

The execution-policy change applies only to the current PowerShell process. It does not change the machine-wide policy.

For macOS/Linux, create and activate the environment with:

    python3 -m venv .venv
    source .venv/bin/activate

Then install dependencies and run Alembic/Uvicorn with `python -m pip`, `python -m alembic`, and `python -m uvicorn` respectively.

Open http://127.0.0.1:8000 for the dashboard and http://127.0.0.1:8000/docs for API docs.

## Database migrations

Alembic is the only schema-management path used by the application. Starting FastAPI no longer runs Base.metadata.create_all() or silently changes a database schema.

- **New/empty database (PowerShell):** run `.\.venv\Scripts\python.exe -m alembic upgrade head` before starting the application.
- **Existing database created by the previous demo:** stop the application and make a verified backup first. Confirm that its payments table matches the initial migration (columns, types, nullability, primary/unique constraints, and indexes). Then run `.\.venv\Scripts\python.exe -m alembic stamp 0001_initial_schema` to record the baseline without executing table-creation SQL, followed by `.\.venv\Scripts\python.exe -m alembic upgrade head`. Migration `0002_tenants_auth` creates the legacy demo tenant and assigns every existing payment to it while replacing global idempotency uniqueness with tenant-scoped uniqueness. The stamp command does not inspect or repair the schema; do not run it against a database whose schema has not been verified.
- **Deployment database:** set DATABASE_URL to the SQLAlchemy URL for the target database and run alembic upgrade head as an explicit deployment/release step before deploying application code. Keep the URL and credentials in the deployment secret manager; never commit credentials.
- **Rollback:** inspect the target revision and backup before using alembic downgrade. A downgrade can remove schema objects and data. The initial migration downgrade drops the payments table and is destructive.

Useful commands (Windows PowerShell):

    .\.venv\Scripts\python.exe -m alembic current
    .\.venv\Scripts\python.exe -m alembic history
    .\.venv\Scripts\python.exe -m alembic upgrade head
    .\.venv\Scripts\python.exe -m alembic check

The application and Alembic both read DATABASE_URL. SQLite is the local default. The SQLAlchemy engine only applies SQLite-specific connection options to SQLite URLs.

## Run tests

Windows PowerShell:

    .\.venv\Scripts\python.exe -m pytest -v

macOS/Linux (with the virtual environment activated):

    python -m pytest -v

The migration tests cover a fresh database upgrade, schema drift against ORM metadata, and baselining an existing demo schema while preserving its payment row.

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
- Implement a proper double-entry ledger, reconciliation, audit logs, and monitoring.
- Add secrets management, TLS, secure deployment configuration, and security review.
- Never store raw card data or CVV; follow the provider's current compliance requirements.

Do not make the demo publicly accessible until the above controls are implemented and reviewed.

## Project structure

    payment-processing-system/
    ├── alembic/
    │   ├── env.py
    │   ├── script.py.mako
    │   └── versions/
    │       └── 0001_initial_schema.py
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
    │   ├── test_migrations.py
    │   └── test_payments.py
    ├── alembic.ini
    ├── .gitignore
    ├── README.md
    └── requirements.txt
