# Payment Processing System

A full-stack educational payment-processing demo with a neon analytics dashboard, FastAPI REST API, SQLAlchemy persistence, simulated payments, idempotency, refunds, and automated tests.

## Important safety and deployment notice

This project is a **simulation**. It does not connect to a bank, card network, UPI provider, or Stripe and it never moves real money. Do not enter real card numbers, CVVs, UPI PINs, or banking credentials. A successful demo response is not a real payment authorization.

The application is intended for local learning. It now includes basic application-level authentication, owner/member authorization, and tenant-scoped demo data, but it is **not production-ready**. Phase 2 adds shared database-backed rate limiting for registration, login, member creation, payment creation, refunds, and authenticated reads. Login uses three keyed-HMAC budgets (IP, IPv4 /24 or IPv6 /64 network prefix, and normalized account) to reduce password spraying while limiting NAT collateral. Large botnets spread across many networks still require MFA, adaptive risk signals, and bot controls. Durable audit trails, a production identity/session architecture, a ledger/reconciliation system, signed provider webhooks, and secrets-management integration remain outstanding. Browser bearer tokens are held in session storage for this demo and remain exposed to browser-side compromise such as XSS. Do not expose it to the public internet or use it to process real payments.

## Features

- Responsive dark navy / neon dashboard
- Create simulated payments using Card, UPI, Wallet, or Net Banking labels
- Transaction history and SQL-aggregated dashboard metrics
- Payment detail endpoint and simulated refunds
- Registration, login, logout, expiring bearer sessions, and PBKDF2 password hashing
- Authenticated profile endpoint; workspace/user/role labels are populated from the signed-in profile
- Owner/member roles with owner-only refunds and tenant membership management
- One-time local admin bootstrap command for the migration-created legacy workspace
- SQLite foreign-key enforcement on every application connection
- Shared database-backed fixed-window rate limits with action-specific policies and HTTP 429 / Retry-After responses
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

The application and Alembic both read DATABASE_URL. SQLite is the local default. The SQLAlchemy engine only applies SQLite-specific connection options to SQLite URLs. Rate-limit identity keys use HMAC-SHA256; set `RATE_LIMIT_HASH_SECRET` to a high-entropy secret through the deployment secret manager outside local development. Set TRUSTED_PROXY_IPS to comma-separated exact proxy IPs or CIDR ranges. Startup fails when `APP_ENV=production` and the secret is missing. The built-in fallback is development-only. Tune action policies with `RATE_LIMIT_<ACTION>_LIMIT` and `RATE_LIMIT_<ACTION>_WINDOW_SECONDS` (actions: `REGISTER`, `LOGIN`, `LOGIN_NETWORK`, `LOGIN_ACCOUNT`, `MEMBER_CREATE`, `PAYMENT_CREATE`, `REFUND`, `READ`).

## Vercel + Supabase deployment

This branch includes a root-level Vercel FastAPI entrypoint, Supabase transaction-pooler connection handling, Vercel client-IP resolution for rate limiting, and a Supabase pg_cron cleanup script. Follow the [Vercel + Supabase deployment guide](docs/deployment/VERCEL_SUPABASE.md) for project setup, environment variables, Alembic migration steps, scheduled cleanup, and verification. Do not deploy publicly or use real payment credentials; this project remains an educational simulation.

## Run tests

Windows PowerShell:

    .\.venv\Scripts\python.exe -m pytest -v

macOS/Linux (with the virtual environment activated):

    python -m pytest -v

The migration tests cover a fresh database upgrade, schema drift against ORM metadata, and baselining an existing demo schema while preserving its payment row.

## API rate limits

Phase 2 uses atomic, database-backed fixed-window counters shared by application workers that use the same database. Registration uses the resolved client IP. Login uses IP, IPv4 /24 or IPv6 /64 network-prefix, and per-account budgets; account and network identities are HMAC-keyed before persistence. Authenticated limits use verified tenant and user IDs.

| Action | Default limit | Window | Scope |
|---|---:|---:|---|
| Registration | 5 | 1 hour | IP |
| Login IP | 60 | 15 minutes | IP |
| Login network | 100 | 15 minutes | IPv4 /24 or IPv6 /64 prefix (HMAC) |
| Login account | 10 | 15 minutes | HMAC of normalized email |
| Member creation | 10 | 1 hour | User + tenant |
| Payment creation | 20 | 1 minute | User + tenant |
| Refund | 5 | 1 minute | User + tenant |
| Authenticated reads | 120 | 1 minute | User + tenant |

A blocked request returns HTTP `429` with an integer `Retry-After` header. If the limiter storage is unavailable, the API fails closed with a generic HTTP `503`. Liveness and readiness probes are exempt. Forwarded IP headers are ignored unless TRUSTED_PROXY_IPS explicitly lists trusted proxy IPs/CIDRs. The application walks the X-Forwarded-For chain from right to left and selects the first untrusted hop. The proxy must overwrite or append the header. Leave the setting empty when no trusted proxy is used; never trust all networks (0.0.0.0/0 or ::/0). Run Uvicorn with --no-proxy-headers so this explicit application allowlist is the only proxy trust policy.

Tune policies using `RATE_LIMIT_<ACTION>_LIMIT` and `RATE_LIMIT_<ACTION>_WINDOW_SECONDS`, where ACTION is `REGISTER`, `LOGIN`, `MEMBER_CREATE`, `PAYMENT_CREATE`, `REFUND`, or `READ`. In production set `APP_ENV=production` and provide a high-entropy `RATE_LIMIT_HASH_SECRET` through the deployment secret manager. Startup fails if the production secret is missing. The development fallback must not be used in production.

Expired bucket cleanup is available as a bounded command: python -m app.maintenance purge-rate-limits --batch-size 1000. Schedule it every 10 minutes. Templates are included at deploy/systemd/ (service and timer) and deploy/windows/cleanup-rate-limits.ps1. On systemd, copy both units to /etc/systemd/system, adjust the user/paths/environment file, then run systemctl daemon-reload and systemctl enable --now payment-rate-limit-cleanup.timer. On Windows, create a Task Scheduler task that runs powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\path\\to\\repo\\deploy\\windows\\cleanup-rate-limits.ps1 every 10 minutes. Ensure the scheduled-task identity has the same DATABASE_URL and RATE_LIMIT_HASH_SECRET environment values as the application. Fixed windows intentionally permit up to approximately twice the configured limit across adjacent windows; a regression test records this boundary behavior. Use a token-bucket/sliding-window limiter at a trusted gateway for strict public-production burst control. Keep host clocks synchronized with NTP. PostgreSQL CI runs a multi-process concurrency test against PostgreSQL 16. Benchmark database contention on the target deployment before increasing limits.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /api/health | Public liveness probe |
| GET | /api/ready | Public database readiness probe |
| POST | /api/auth/register | Publicly create a new tenant and its first owner; IP rate-limited |
| POST | /api/auth/login | Public login; returns a bearer token; IP, network-prefix, and account rate-limited |
| GET | /api/auth/me | Authenticated user and workspace profile |
| POST | /api/auth/logout | Authenticated session revocation |
| POST | /api/tenant/members | Owner-only member creation; user rate-limited |
| GET | /api/dashboard | Authenticated, tenant-scoped dashboard metrics; read rate-limited |
| GET | /api/payments | Authenticated, tenant-scoped payment list; read rate-limited |
| POST | /api/payments | Authenticated, tenant-scoped simulated payment creation; user rate-limited |
| GET | /api/payments/{payment_id} | Authenticated payment detail; cross-tenant records return 404; read rate-limited |
| POST | /api/payments/{payment_id}/refund | Owner-only refund of a successful demo payment; user rate-limited |

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

## Recover access to pre-Phase-1 demo payments

Migration `0002_tenants_auth` preserves old demo payments in the `Legacy demo workspace`. It intentionally does not invent an owner identity or password. To access those records, an administrator with trusted local access to the migrated database must run the one-time bootstrap command. This command is not an HTTP endpoint and refuses to run if the legacy workspace already has a user.

PowerShell example (run from the repository root after migration):

    $env:LEGACY_OWNER_NAME = "Legacy Workspace Owner"
    $env:LEGACY_OWNER_EMAIL = "legacy-owner@example.com"
    $env:LEGACY_OWNER_PASSWORD = "use-a-unique-password-of-at-least-12-characters"
    .\.venv\Scripts\python.exe -m app.bootstrap_legacy_owner
    Remove-Item Env:LEGACY_OWNER_NAME, Env:LEGACY_OWNER_EMAIL, Env:LEGACY_OWNER_PASSWORD

Use a unique password, do not commit it, and run this only on a trusted machine against the intended `DATABASE_URL`.

## Production engineering still required

Before any real payment integration or public deployment:

- Complete deployment-specific activation and validation for Phase 2 rate limiting (trusted proxy allowlist, cleanup scheduler, target-database load benchmark, and monitoring). The application implementation and PostgreSQL CI concurrency checks are in PR #5.
- Add durable, append-only audit logging for sensitive business actions.
- Implement a balanced double-entry ledger and reconciliation.
- Integrate an authorized payment service provider using its official SDK and sandbox.
- Verify signed provider webhooks and make webhook processing idempotent.
- Add PostgreSQL concurrency and failure-injection tests.
- Add monitoring/alerting, backups and restore drills, TLS, secrets management, deployment/rollback controls, and independent security review.
- Never store raw card data or CVV; follow the provider's current compliance requirements.

Do not make the demo publicly accessible until the above controls are implemented and reviewed.

## Project structure

    payment-processing-system/
    ├── alembic/
    │   ├── env.py
    │   ├── script.py.mako
    │   └── versions/
    │       ├── 0001_initial_schema.py
    │       ├── 0002_tenants_auth_and_scoped_idempotency.py
    │       └── 0003_rate_limit_buckets.py
    ├── app/
    │   ├── __init__.py
    │   ├── config.py
    │   ├── database.py
    │   ├── main.py
    │   ├── proxy.py
    │   ├── rate_limit.py
    │   ├── maintenance.py
    │   ├── bootstrap_legacy_owner.py
    │   ├── models.py
    │   ├── schemas.py
    │   └── services.py
    ├── frontend/
    │   ├── index.html
    │   ├── styles.css
    │   └── app.js
    ├── deploy/
    │   ├── systemd/
    │   │   ├── payment-rate-limit-cleanup.service
    │   │   └── payment-rate-limit-cleanup.timer
    │   └── windows/
    │       └── cleanup-rate-limits.ps1
    ├── scripts/
    │   └── benchmark_rate_limit.py
    ├── supabase/
    │   └── cron/
    │       └── purge_rate_limit_buckets.sql
    ├── docs/
    │   └── deployment/
    │       └── VERCEL_SUPABASE.md
    ├── tests/
    │   ├── conftest.py
    │   ├── test_auth_tenants.py
    │   ├── test_migrations.py
    │   ├── test_payments.py
    │   └── test_rate_limiting.py
    ├── main.py
    ├── vercel.json
    ├── .python-version
    ├── alembic.ini
    ├── .gitignore
    ├── README.md
    └── requirements.txt
