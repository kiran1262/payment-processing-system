# Production Readiness Plan

**Project:** Payment Processing System  
**Tracking PR:** [#2 — production-readiness roadmap](https://github.com/kiran1262/payment-processing-system/pull/2)  
**Status:** Phases 0 and 1 are implemented and merged in PRs #3 and #4. Phase 2 application implementation and automated CI verification are complete in draft PR #5; deployment-specific proxy/scheduler activation and target-environment benchmarking remain. Phases 3–6 remain planned. The Phase 2 master review and implementation record is `docs/phase-2/PHASE_2_REVIEW_AND_IMPLEMENTATION.md`. This plan tracks production-readiness work, not a claim that the demo is production-ready.  
**Rule:** Work on one item at a time. Do not combine unrelated security, schema, and payment-accounting changes into one large patch.

This application is currently an educational payment simulation. Do not expose it publicly or use it to process real money until the required controls have been implemented, tested, and independently reviewed.

## Current implementation status

| Phase | Status | Evidence / remaining gate |
|---|---|---|
| 0. Alembic migration foundation | **Implemented** | PR #3 is merged. Alembic owns schema changes; startup does not call `create_all`. Migration tests cover fresh upgrade, existing-row preservation, and metadata drift. |
| 1. Authentication, authorization, tenant isolation | **Complete — PR #4 merged** | Registration/login/logout, 12-hour revocable bearer sessions, owner/member roles, tenant-scoped payment operations and idempotency, migration 0002, SQLite FK enforcement, local legacy-owner bootstrap, owner-aware refund controls, dynamic profile identity, and regression tests are implemented. Browser E2E coverage remains outstanding. |
| 2. Rate limiting and abuse controls | **Implementation + CI verified — PR #5 draft** | Shared atomic SQLite/PostgreSQL fixed-window limits, IP/network/account login controls, bounded cleanup command and scheduler templates, trusted-proxy allowlist support, and regression tests. PostgreSQL 16 multi-process CI passed. Deployment-specific proxy/scheduler activation, target-database benchmark, policy tuning, and monitoring remain operational gates. See the Phase 2 master record. |
| 3. Audit logging | **Not started** | Append-only, transactionally consistent business audit events. |
| 4. Ledger and reconciliation | **Not started** | Immutable balanced double-entry postings and provider reconciliation. |
| 5. Provider integration and webhook verification | **Not started** | Provider selection, signature/replay verification, durable event deduplication. |
| 6. PostgreSQL concurrency and failure-injection tests | **Not started** | Real PostgreSQL integration tests, concurrent operations, rollback and duplicate-event tests. |

Phase 1 does not make this application a production payment platform. Session storage remains XSS-exposed, and no real payment provider or funds movement is involved.

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
- Define separate limits for authentication attempts, member creation, payment creation, refunds, and authenticated reads. Document webhook ingress limits for Phase 5 after a provider is selected.
- Use shared storage for limits across application workers; an in-process counter is not sufficient in a multi-worker deployment.
- Return 429 with a useful `Retry-After` value.
- Keep liveness/readiness probes exempt from application user limits; document trusted provider callback handling as a Phase 5 requirement.
- Test burst behavior, reset windows, and multi-worker consistency.

**Implementation and CI acceptance — complete in PR #5**
- Limits are enforced using shared atomic database counters; PostgreSQL 16 multi-process CI verifies concurrent behavior.
- Registration, login (IP/network/account), member creation, payment creation, refunds, and authenticated reads have explicit policies.
- 429/Retry-After and fail-closed storage behavior are tested.

**Deployment acceptance — still required**
- Enable cleanup scheduler and configure the actual trusted proxy allowlist.
- Benchmark the target database/worker topology, tune policies, and add operational monitoring.
- Provider retry handling remains a separate Phase 5 concern.

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

- [x] Existing payment demo bug-fix PR #1 merged; its pytest CI run passed.
- [x] 0. Alembic migration foundation
- [x] 1. Authentication, authorization, and tenant isolation
- [x] 2. API rate limiting implementation and automated CI verification (PR #5 draft; deployment activation remains)
- [ ] 3. Audit logging
- [ ] 4. Ledger and reconciliation
- [ ] 5. Provider integration and webhook verification
- [ ] 6. PostgreSQL concurrency and failure-injection tests

Update this checklist only after each phase has code, tests, and review evidence.
