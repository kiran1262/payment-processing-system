# Payment Processing System

A full-stack educational payment-processing demo with a neon analytics dashboard, FastAPI REST API, SQLAlchemy persistence, payment simulation, idempotency, refunds, and automated tests.

## Important safety note

This project is a **simulation**. It does not connect to a bank, card network, UPI provider, or Stripe and it never moves real money. Do not enter real card numbers, CVVs, UPI PINs, or banking credentials. A successful demo response is not a real payment authorization.

## Features

- Responsive dark navy / neon dashboard inspired by the supplied design
- Create simulated payments using Card, UPI, Wallet, or Net Banking labels
- Transaction history and live KPI summaries
- Payment detail endpoint and simulated refunds
- Idempotency-Key support to avoid duplicate payment records
- SQLite database created automatically
- FastAPI interactive API documentation at `/docs`
- Pytest suite for core payment flows

## Architecture

```text
Browser (HTML / CSS / JavaScript)
          |
          | HTTP / JSON
          v
FastAPI application
  |-- REST endpoints
  |-- Payment service
  |-- Idempotency handling
  |-- Refund state transition
          |
          v
SQLAlchemy ORM ---- SQLite (payment.db)
```

## Requirements

- Python 3.11+
- Windows PowerShell (commands below) or macOS/Linux

## Run on Windows PowerShell

```powershell
# 1. Move into the extracted project folder
cd .\payment-processing-system

# 2. Create and activate a virtual environment
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

# If PowerShell blocks activation, run this once in the current terminal:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Start the web application
python -m uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000** for the dashboard and **http://127.0.0.1:8000/docs** for the API docs.

## Run tests

Open a second PowerShell terminal, activate the environment, then run:

```powershell
python -m pytest -v
```

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/dashboard` | Dashboard metrics |
| GET | `/api/payments` | List recent payments |
| POST | `/api/payments` | Create a simulated payment |
| GET | `/api/payments/{payment_id}` | Retrieve a payment |
| POST | `/api/payments/{payment_id}/refund` | Refund a successful demo payment |

### Create payment example

```powershell
$body = @{
  customer_name = "Alex Morgan"
  customer_email = "alex@example.com"
  amount = 1499.00
  currency = "INR"
  method = "UPI"
  description = "Order #1001"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/payments `
  -ContentType "application/json" `
  -Headers @{"Idempotency-Key"="demo-order-1001"} `
  -Body $body
```

### Demo decline scenario

For learning purposes only, amounts ending in `.99` are declined. For example, `99.99` produces a `declined` status. Other valid amounts are simulated as successful. This is not a real issuer or fraud decision.

## Project structure

```text
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
```

## GitHub setup

Create an empty GitHub repository named `payment-processing-system`, then:

```powershell
git init
git add .
git commit -m "Build Payment Processing demo"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/payment-processing-system.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username.

## Production engineering work still required

Before handling real payments, integrate an authorized payment service provider using its official SDK and test environment; verify signed webhooks; add authentication, authorization, rate limits, audit logs, secrets management, database migrations, proper ledger accounting, reconciliation, monitoring, and security review. Never store raw card data or CVV. Follow the provider's current compliance requirements.

## Payment request troubleshooting

The frontend sends payment data as JSON and preserves both the `Content-Type: application/json` header and the `Idempotency-Key` header. If the API rejects a request, the dashboard now displays readable FastAPI validation details instead of `[object Object]`.

If you already have the server running, save the updated files and refresh the browser. FastAPI/Uvicorn with `--reload` will reload backend changes automatically; browser JavaScript changes require a hard refresh (`Ctrl+Shift+R`).
