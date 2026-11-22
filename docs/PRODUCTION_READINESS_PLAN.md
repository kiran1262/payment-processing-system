# Production Readiness Plan

**Project:** Payment Processing System  
**Tracking branch:** `fix/payment-processing-review`  
**Status:** Planning only — none of the production-readiness items below is implemented by this document.  
**Rule:** Work on one item at a time. Do not combine unrelated security, schema, and payment-accounting changes into one large patch.

This application is currently an educational payment simulation. Do not expose it publicly or use it to process real money until the required controls have been implemented, tested, and independently reviewed.

## Current code map and reuse-first rules

Read these existing pieces before adding anything:

| Existing code | Current responsibility | Reuse when implementing |
|---|---|---|
| `app/database.py:get_db` | Creates and closes a SQLAlchemy session per request | Keep one shared session dependency for new routes/services. Do not create a second session factory. |
| `app/database.py:Base` | Shared SQLAlchemy declarative metadata | Use this metadata for Alembic; do not introduce a second ORM base. |
| `app/models.py:Payment` | Current payment persistence | Extend only for payment-owned fields such as tenant ownership. Do not turn this row into an accounting ledger or webhook event store. |
| `app/schemas.py:PaymentCreate` | Pydantic request validation | Keep trust-boundary validation in the existing schema layer. Add only fields required by the feature. |
| `app/main.py` | FastAPI routes and dependency wiring | Reuse FastAPI dependency injection for authentication, tenant context, and rate-limit enforcement. Keep route handlers thin. |
| `app/services.py:create_payment` | Payment creation and idempotency behavior | Preserve the current domain path; extend its transaction boundary rather than duplicating payment creation in routes. |
| `app/services.py:refund_payment` | Conditional succeeded-to-refunded transition | Keep refund state changes in one shared service path. |
| `app/services.py:dashboard_stats` | SQL aggregate metrics | Extend with tenant-scoped query filters; do not load all rows into Python. |
| `app/main.py:payment_json` | Existing API serialization | Reuse it unless the API contract requires a deliberate response-schema migration. |
| `tests/conftest.py:client` | FastAPI test client and `get_db` override | Reuse the dependency override pattern. Add a separate PostgreSQL integration fixture for true concurrency tests; SQLite's in-memory StaticPool fixture is not enough to prove production locking behavior. |
| `.github/workflows/tests.yml` | Pytest CI workflow | Extend this workflow with focused jobs/services only when a feature needs them. |

**Ponytail implementation rule:** read the callers and data flow first; reuse existing code; prefer the standard library, platform, and already-installed dependencies; avoid speculative abstractions. Never simplify away security, validation, transaction safety, accessibility, or tests.

## Work order

Complete the phases in order. Each phase should be its own focused change with tests and a review before starting the next. Dependencies between phases are intentional.

### 0. Database migration foundation — Alembic

**Why first:** authentication, tenants, audit events, ledger entries, and webhook events all require safe schema evolution. The app currently calls `Base.metadata.create_all()` at startup, which is suitable only for the small local demo and does not upgrade existing databases safely.

**Inspect/reuse**
- Reuse `Base` from `app/database.py` and existing models from `app/models.py`.
- Replace production reliance on startup `create_all()` with explicit migrations. Keep a clearly isolated local-demo bootstrap only if tests prove it is still needed.
- Reuse the existing `DATABASE_URL` configuration; do not hardcode a second connection string.

**Tasks**
- Add Alembic configuration and an environment that imports the existing `Base.metadata`.
- Create an initial migration matching the current schema, then test upgrade from an empty database and from the current schema.
- Make migration execution an explicit deployment step, not an implicit request-startup side effect.
- Decide how SQLite demo databases and the production database (recommended PostgreSQL) are handled.

**Done when**
- Fresh database upgrades to head.
- A database at the previous revision upgrades without losing payment rows.
- CI checks migration generation/drift and runs migration tests.
- Application startup does not silently mutate a production schema.

### 1. Authentication, authorization, and tenant isolation

**Why together:** tenant filtering without a trusted authenticated identity is not a security boundary. Every payment read/write must be scoped to the authenticated tenant.

**Inspect/reuse**
- Reuse FastAPI dependency injection in `app/main.py`.
- Reuse `get_db`; pass the same request session through auth lookup and business services.
- Reuse existing `Payment` rows, adding a tenant foreign key only through a migration.
- Reuse Pydantic schemas for request validation. Never accept a tenant ID from an untrusted request body as proof of ownership.

**Tasks**
- Define the authentication model and trusted principal dependency (token/session validation, expiry, revocation/rotation policy).
- Define roles/permissions and deny-by-default authorization.
- Add tenant ownership to payment records and scope list, detail, refund, dashboard, and idempotency queries to the authenticated tenant.
- Make idempotency uniqueness tenant-aware so two tenants cannot collide or replay each other's records.
- Ensure missing/invalid credentials return 401 and insufficient permission returns 403 without leaking whether another tenant's payment exists.
- Add tests for cross-tenant reads, refunds, dashboard leakage, and idempotency-key collisions.

**Done when**
- Every protected route requires a verified principal.
- No tenant can read, mutate, count, or replay another tenant's payment by guessing an ID/key.
- Tests cover each endpoint and both allowed and denied roles.

### 2. API rate limiting and abuse controls

**Inspect/reuse**
- Apply enforcement at the API boundary in `app/main.py` or the deployment gateway; do not sprinkle independent counters through payment services.
- Reuse the authenticated principal/tenant context from phase 1 for per-user and per-tenant limits.
- Prefer an existing gateway/reverse-proxy capability when deployment provides one. Add a library only if the deployment cannot provide the required limits.

**Tasks**
- Define separate limits for authentication attempts, payment creation, refunds, reads, and webhook ingress.
- Use shared storage for limits across application workers; an in-process counter is not sufficient in a multi-worker deployment.
- Return 429 with a useful `Retry-After` value.
- Decide how trusted provider callbacks and internal health checks are treated.
- Test burst behavior, reset windows, and multi-worker consistency.

**Done when**
- Limits are enforced consistently across all workers and instances.
- Expensive or sensitive endpoints have explicit policies.
- Legitimate provider retries are not accidentally blocked.

### 3. Audit logging

**Inspect/reuse**
- Reuse the request-scoped SQLAlchemy session and transaction boundaries from `get_db`, `create_payment`, and `refund_payment`.
- Keep operational logs (diagnostics) separate from durable business audit events.
- Do not log passwords, access tokens, card data, CVV, UPI PINs, or full sensitive payloads.

**Tasks**
- Define a minimal append-only audit event model: actor, tenant, action, target type/ID, outcome, timestamp, correlation/request ID, and safe metadata.
- Write audit events in the same database transaction as the state change when atomicity is required.
- Record authentication/authorization failures and privileged actions without leaking secrets.
- Define retention, access controls, export, and tamper-resistance requirements.

**Done when**
- Payment/refund/permission changes have attributable audit events.
- A failed business transaction does not leave a misleading success audit record.
- Tests verify both event creation and rollback behavior.

### 4. Proper payment ledger and reconciliation

**Do not model a ledger by adding more mutable balance fields to `Payment`.** Payment lifecycle state and accounting entries are different concepts.

**Inspect/reuse**
- Reuse `Payment.amount_paise` as the exact integer minor-unit source and the existing database transaction/session.
- Reuse `create_payment` and `refund_payment` as the business entry points, but make ledger postings part of the same atomic transaction.
- Keep `dashboard_stats` as a read/query layer; derive financial totals from ledger entries where appropriate.

**Tasks**
- Define accounts and immutable, balanced debit/credit ledger entries with currency and idempotent source references.
- Define posting rules for authorization/capture, settlement, fees, refunds, reversals, and failures with a payment/accounting domain expert.
- Prevent updates/deletes of posted entries; correct mistakes with reversing entries.
- Add invariants: every journal balances per currency, each source event posts at most once, and totals reconcile.
- Build reconciliation against provider settlement/transaction reports, with discrepancy states and an operator workflow.
- Define how historical demo payments are treated; never invent real accounting entries for simulated transactions.

**Done when**
- All supported financial events create balanced, immutable postings.
- Duplicate events cannot double-post.
- Reconciliation reports explain missing, duplicate, and amount-mismatched records.
- Property/invariant tests cover all posting and reversal paths.

### 5. Payment provider integration and webhook verification

**Important:** this phase is not just adding a webhook endpoint. Provider-specific signing and event semantics must follow the chosen provider's official documentation.

**Inspect/reuse**
- Reuse the existing payment service and transaction boundaries, but keep provider API calls behind a small provider-specific adapter only when an actual provider is selected.
- Use a dedicated provider-event record and unique provider event ID. Do not reuse `Payment.idempotency_key` for webhook deduplication; the keys have different scopes.
- Reuse the audit-event mechanism from phase 3 and ledger posting rules from phase 4.

**Tasks**
- Select the provider and implement its official signature verification against the raw request body.
- Validate timestamp/replay windows and secret rotation; never trust a client-supplied payment status.
- Persist event IDs before processing and handle duplicate, delayed, and out-of-order events safely.
- Make webhook processing retryable and idempotent; acknowledge only after durable acceptance/processing according to provider guidance.
- Verify amount, currency, provider reference, and tenant/payment mapping before applying state transitions.
- Test invalid signatures, replay, duplicate delivery, delayed delivery, out-of-order events, and provider timeouts.

**Done when**
- Invalid or replayed events cannot change payment state.
- Duplicate delivery has one durable effect.
- Provider state, internal payment state, audit trail, and ledger remain consistent.

### 6. Dedicated concurrency and failure-injection tests

**Why last as a production gate:** the tests should validate the real database and all final transaction boundaries, not only SQLite's in-memory behavior.

**Inspect/reuse**
- Reuse `tests/conftest.py` dependency override pattern and existing payment tests.
- Keep fast SQLite tests for ordinary request behavior.
- Add PostgreSQL-backed integration tests for row locks, unique constraints, transactions, and concurrent writers.
- Reuse existing idempotency/refund service paths rather than testing a separate implementation.

**Tasks**
- Run simultaneous create requests with the same idempotency key and identical payload: exactly one payment row and equivalent responses.
- Run simultaneous requests with the same key and different payloads: one winner, all conflicting requests return 409, no unhandled 500.
- Race two refunds: one state transition and one ledger refund posting.
- Deliver the same webhook concurrently: one durable event effect and one set of ledger postings.
- Inject database failures between writes and prove the whole transaction rolls back.
- Exercise multiple application workers/processes against the same PostgreSQL database.

**Done when**
- Tests are deterministic, run in CI against PostgreSQL, and assert database state—not just HTTP status.
- No duplicate payments, refunds, webhook effects, or ledger postings occur under the tested races.
- Failure injection proves that partial financial state cannot be committed.

## Definition of production-ready

Do not mark this project production-ready until all phases are complete, migrations are repeatable, security and accounting controls have been reviewed, CI passes against the production database engine, secrets/TLS/monitoring/backup/restore procedures exist, and a payment-provider sandbox certification path has been completed.

The current project remains a simulation until a real provider integration and its compliance requirements are deliberately implemented.

## Progress

- [x] Existing payment demo bug-fix PR opened and CI verified on its latest commit.
- [ ] 0. Alembic migration foundation
- [ ] 1. Authentication, authorization, and tenant isolation
- [ ] 2. API rate limiting
- [ ] 3. Audit logging
- [ ] 4. Ledger and reconciliation
- [ ] 5. Provider integration and webhook verification
- [ ] 6. PostgreSQL concurrency and failure-injection tests

Update this checklist only after each phase has code, tests, and review evidence.
