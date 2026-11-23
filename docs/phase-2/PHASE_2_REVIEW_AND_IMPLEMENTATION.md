# Phase 2 — Rate Limiting and Abuse Controls
> **Single source of truth for Phase 2 review, implementation, tests, decisions, and remaining work.**
>
> Project: `kiran1262/payment-processing-system`  
> Base: `main` (PR #4 merged)  
> Working branch: `feat/phase-2-rate-limiting-abuse-controls`  
> Status: **Implementation in progress; CI green; final review pending**  
> Scope: API rate limiting and abuse controls. This document is updated as findings are verified and fixes land.

---

## 1. Project purpose and safety boundary

This repository is an educational payment simulation built with FastAPI, SQLAlchemy, Alembic, SQLite for local development, and a browser frontend. It does not connect to a bank, card network, UPI provider, Stripe, or Razorpay and it does not move real money.

Phase 2 adds abuse controls; it does **not** make the application production-ready. Do not expose the demo publicly or use real customer/payment credentials.

## 2. Verified project baseline

- PR #1: payment validation, idempotency, refunds, dashboard query fixes — merged.
- PR #2: production-readiness roadmap and Ponytail skills — merged.
- PR #3: Alembic migration foundation — merged.
- PR #4: authentication, authorization, tenant isolation, legacy workspace bootstrap, SQLite foreign-key enforcement, owner-aware frontend controls, dynamic profile identity — merged.
- Phase 1 CI evidence recorded in PR #4: 34 pytest tests passed. Browser E2E testing was not part of that CI run.
- The application still uses bearer tokens in browser `sessionStorage`; this remains exposed to XSS/browser compromise.
- Phase 2 must preserve tenant isolation, role checks, idempotency behavior, payment/refund semantics, and migration discipline.

## 3. Repository inventory and reuse map

| Area | Existing files | Phase 2 relevance / reuse |
|---|---|---|
| API boundary | `app/main.py` | Apply rate limits at the HTTP boundary; keep handlers thin. |
| Authentication | `app/auth.py` | Reuse verified principal and owner dependency; never trust caller-supplied tenant IDs. |
| Database | `app/database.py`, `app/config.py` | Reuse one engine, session factory, `get_db`, and configured `DATABASE_URL`. |
| ORM | `app/models.py` | Add a rate-limit bucket model only if the selected shared-store design requires it. |
| Schemas/services | `app/schemas.py`, `app/services.py` | Do not duplicate payment/refund logic; rate limiting should not alter domain semantics. |
| Migrations | `alembic/env.py`, `alembic/versions/*` | All schema changes must use Alembic; never add startup `create_all`. |
| Tests | `tests/conftest.py`, `tests/test_auth_tenants.py`, `tests/test_payments.py`, `tests/test_migrations.py` | Reuse the existing FastAPI client and DB override; add deterministic rate-limit tests. |
| Frontend | `frontend/app.js`, `frontend/index.html`, `frontend/styles.css` | Display a useful retry message for 429 without exposing internals; preserve idempotency key on retries. |
| CI/docs | `.github/workflows/tests.yml`, `README.md`, `docs/*` | Extend CI only for checks that can be reliably run; update the master record and user-facing docs. |

### Reuse-first rules

1. Inspect call sites and dependency wiring before adding code.
2. Reuse FastAPI dependency injection and the request-scoped SQLAlchemy session.
3. Use a shared cross-worker store. An in-process dictionary/counter is not acceptable.
4. Keep rate-limit identity server-derived: IP for pre-authentication endpoints; authenticated user and tenant for protected endpoints.
5. Keep limits separate by action and configurable/testable.
6. Return HTTP 429 with a standards-compatible `Retry-After` header.
7. Do not rate-limit liveness/readiness probes by default; document the deployment-gateway alternative.
8. Never trust arbitrary `X-Forwarded-For` from the public internet. Only use proxy headers when the deployment explicitly configures trusted proxy hops.
9. Do not log passwords, bearer tokens, full request bodies, or raw rate-limit keys.
10. Do not weaken existing validation, auth, idempotency, refund, migration, or tenant-isolation tests.

## 4. Phase 2 objectives and acceptance criteria

### Required endpoint classes

| Endpoint class | Abuse risk | Identity scope |
|---|---|---|
| Registration | Automated tenant/account creation | Client IP |
| Login | Password guessing and PBKDF2 CPU exhaustion | Client IP; optionally account/email bucket with privacy-safe digest |
| Payment creation | Automated transaction spam / DB load | Authenticated user and tenant |
| Refund | Repeated privileged mutation attempts | Authenticated user and tenant |
| Payment reads, detail, dashboard | Enumeration and expensive query load | Authenticated user and tenant |
| Webhook ingress | Provider retry storms / malicious traffic | Provider/event policy; endpoint does not exist yet and must be designed in Phase 5 |

### Acceptance criteria

- Limits are enforced consistently across app workers/instances using a shared store.
- Different action classes have independent policies.
- Authenticated limits are scoped using verified user/tenant identity, not request-body fields.
- 429 responses include a positive, bounded `Retry-After` value.
- Limit windows reset correctly and boundary behavior is deterministic.
- Concurrent requests cannot bypass limits through lost updates.
- A rate-limit backend/database failure follows an explicit fail-closed or fail-open policy per endpoint class; it must never silently bypass controls.
- Provider webhook retries will not be blocked by generic user limits when Phase 5 is implemented.
- Tests verify allowed requests, blocked requests, reset, independent buckets, identity isolation, concurrency/atomicity where feasible, and failure behavior.
- Existing Phase 1 and payment tests remain green.

## 5. Initial full-project review — findings to validate

The following are confirmed from the current `main` source snapshot unless marked as design risk:

| ID | Finding / risk | Severity | Evidence / required action |
|---|---|---|---|
| P2-01 | No application-level rate limiting exists on registration, login, payment creation, refunds, or reads. | High | Current route definitions have no rate-limit dependency or middleware. Add action-specific policies. |
| P2-02 | Login performs PBKDF2 password verification without an attempt throttle. | High | `app/auth.py` uses 310,000 PBKDF2 iterations; repeated invalid login attempts can consume CPU. Apply pre-auth IP throttling and privacy-safe account throttling. |
| P2-03 | Public registration can create tenants/users without an abuse control. | High | `POST /api/auth/register` is public. Add IP-scoped limits and document any future invite/verification controls as out of scope. |
| P2-04 | Payment creation and refund endpoints can be repeatedly invoked by an authenticated account. | High | `POST /api/payments` and refund route currently have no action-specific throttle. Keep idempotency separate; a rate limit is not an idempotency mechanism. |
| P2-05 | Read endpoints have no explicit request budget. | Medium | Payment list is bounded to 250 rows, but repeated reads/dashboard aggregates can still create load. Add per-user/tenant read budgets. |
| P2-06 | Proxy/IP trust policy is unspecified. | High | The application currently has no trusted-proxy configuration. Never accept caller-controlled forwarded headers by default. |
| P2-07 | Shared-store choice and outage behavior are undefined. | High | A process-local counter would fail across workers. Select a shared, atomic storage strategy and explicitly test backend failures. |
| P2-08 | Rate-limit bucket lifecycle/cleanup is undefined. | Medium | A persistent DB-backed implementation needs expiry cleanup and bounded storage growth; Redis requires TTLs. |
| P2-09 | Frontend 429 handling needs verification. | Medium | Ensure users see a safe retry message and do not lose the pending idempotency key. |
| P2-10 | Webhook ingress is not implemented. | Informational / future | Define a separate provider-aware policy in Phase 5; do not invent a public webhook route in Phase 2. |

### Additional design risks to resolve before implementation

- Fixed-window boundary bursts versus sliding-window/token-bucket behavior.
- IP address handling for IPv4/IPv6 and NAT-shared clients.
- Whether login limits also use a normalized-email digest; avoid revealing account existence through different 429 responses.
- Whether authenticated read limits use one combined bucket or separate list/detail/dashboard buckets.
- Whether rate-limit storage shares the primary transactional database. If it does, account for database contention and outage coupling.
- Cleanup strategy must not race with active buckets or reset their counters.
- Return `Retry-After` as integer seconds and avoid leaking raw identity/key data.
- Ensure dependency ordering means unauthenticated requests are rejected before consuming authenticated user buckets, and valid user identity is resolved before tenant/user limits are applied.

## 6. Proposed implementation direction — pending final code review

Preferred initial approach: **database-backed atomic fixed-window buckets** in the already-configured shared SQL database, provided implementation can use dialect-native atomic upsert for SQLite and PostgreSQL without lost updates. This avoids adding a new external Redis service for the educational local setup while remaining shared across workers using the same database.

Before committing to this choice, verify:
- SQLAlchemy and SQLite/PostgreSQL dialect support in installed versions.
- Atomic upsert semantics for both supported dialects.
- How to keep a rate-limit increment transaction isolated from payment business transactions.
- Lock/contention behavior and handling of `SQLAlchemyError`.
- Migration compatibility and test behavior on both dialects.

If the database-backed approach cannot meet atomicity or outage isolation, stop and document the reason before switching to Redis or a gateway-managed limiter. Do not claim production-grade distributed limiting based only on SQLite tests.

### Initial policy proposal (must be calibrated and documented)

| Action | Initial limit proposal | Window | Scope |
|---|---:|---:|---|
| Register | 5 | 1 hour | IP |
| Login | 10 | 15 minutes | IP, plus privacy-safe account digest if implemented |
| Payment create | 20 | 1 minute | user + tenant |
| Refund | 5 | 1 minute | user + tenant |
| Reads (list/detail/dashboard/profile) | 120 | 1 minute | user + tenant |

These are conservative demo defaults, not universal production recommendations. Keep limits configurable and tests independent of wall-clock sleeps.

## 7. Test plan

- [x] Registration: blocked request returns 429 before tenant creation handler runs.
- [x] Login: invalid credentials count toward the IP budget; a subsequent attempt is blocked. Dependency ordering prevents the login handler from running after the limit is exceeded.
- [x] Login: same socket IP limit applies across different target emails; spoofed `X-Forwarded-For` does not change identity.
- [x] Payment creation: authenticated user/tenant limit applies; another authenticated tenant has an independent bucket.
- [x] Refund and owner-only member creation have independent action budgets; existing member 403 authorization tests remain green.
- [x] Profile, dashboard, payment list, and payment detail share the authenticated read budget; existing list-size validation remains green.
- [x] 429 response includes positive integer `Retry-After` and a generic error body.
- [x] Fixed-window reset and retry countdown are deterministic under an injected timestamp.
- [ ] Concurrent increments cannot exceed the configured allowance through lost updates.
- [x] Limiter storage failure fails closed with generic 503 and `Retry-After: 5`.
- [x] Spoofed `X-Forwarded-For` is ignored; direct ASGI socket peer is used.
- [x] Expired bucket cleanup removes expired buckets; a live bucket remains until its expiry.
- [x] Frontend reads `Retry-After` and displays retry guidance; payment idempotency persistence remains covered by the existing Phase 1 regression test.
- [x] Existing auth, tenant, migration, payment, refund, and idempotency tests pass in the full suite.
- [x] Alembic fresh upgrade and model drift check pass in the migration test suite.

### Not yet proven / remaining acceptance work

- [ ] PostgreSQL multi-process concurrency and high-contention tests (tracked for Phase 6).
- [ ] Schedule bucket cleanup in deployment operations; no scheduler is wired into this demo.
- [ ] Decide production trusted-proxy hop configuration.
- [ ] Calibrate policies against expected traffic and production infrastructure.

## 8. Phase 2 implementation log

| Date | Change | Tests / evidence | Status |
|---|---|---|---|
| 2026-11-23 | Created this master record and began source audit on a branch from merged Phase 1 `main`. | PR #4 verified merged; source inventory captured. | Complete |
| 2026-11-23 | Added atomic fixed-window limiter using shared SQL database upserts, rate-limit bucket model/migration 0003, route dependencies, safe 429/503 behavior, frontend Retry-After guidance, and focused tests. | Initial CI run: 41 passed; expanded route coverage, HMAC identity pseudonymization, and frontend syntax CI check added afterward. Latest run pending. | In progress |

## 9. Current implementation details and residual review

### Implemented in the working branch

- Added `RateLimitBucket` model and Alembic revision `0003_rate_limit_buckets`.
- Added `app/rate_limit.py` with atomic SQLite/PostgreSQL upsert counters, HMAC-SHA256 bucket-key pseudonyms (keyed by `RATE_LIMIT_HASH_SECRET`), fixed windows, 429 responses with `Retry-After`, fail-closed 503 behavior when the limiter store is unavailable, and an explicit expired-bucket cleanup function.
- Added policies: registration 5/hour/IP; login 10/15 minutes/IP; member creation 10/hour/user+tenant; payment creation 20/minute/user+tenant; refunds 5/minute/user+tenant; reads 120/minute/user+tenant.
- Applied limits to registration, login, member creation, profile, dashboard, payment list/detail/create, and refund routes. Health and readiness probes remain exempt.
- Frontend displays retry guidance for 429. Payment idempotency key remains in session storage after a rejected request.
- Added tests for fixed-window enforcement/reset, hashed bucket identifiers, cleanup, login/IP throttling, forwarded-header spoof resistance, payment throttling, per-user isolation, read limits, and fail-closed storage errors.

### Residual risks / items not yet proven

- GitHub Actions passed **45 tests, 1 warning** on code/test commit `9bc3984559092183cc3e4a83f105a4108601c308`; the later PR-head commit `f5f95b7098c4c3d6280cb1b730af86eeb08e15f3` also passed 45 tests and `node --check frontend/app.js`. The warning is a Starlette deprecation warning from the current httpx/TestClient integration.
- Fixed-window counters permit a burst across adjacent window boundaries; token-bucket/sliding-window behavior may be preferable for a production deployment.
- Window boundaries use application-process clocks. Multi-instance deployments must maintain clock synchronization; clock skew can cause inconsistent window assignment.
- The shared limiter currently uses the primary database. This creates database contention and means limiter availability is coupled to database availability.
- Expired-bucket cleanup is exposed as a function but no scheduler/maintenance command is wired yet; production operations must schedule it.
- `RATE_LIMIT_HASH_SECRET` must be set to a high-entropy secret in production; the built-in fallback is development-only. Rotating it resets the effective rate-limit key namespace. Policies can be tuned with `RATE_LIMIT_<ACTION>_LIMIT` and `RATE_LIMIT_<ACTION>_WINDOW_SECONDS` environment variables.
- Client IP uses the direct ASGI socket peer. Forwarded headers are intentionally ignored; deployments behind a reverse proxy need explicit trusted-proxy configuration at the edge.
- Login is throttled by IP, not by account/email. Distributed password spraying across many IPs remains a residual risk; account-scoped throttling must be designed carefully to avoid attacker-induced account lockout.
- Webhook ingress does not exist and remains a Phase 5 concern.
- SQLite tests do not prove PostgreSQL multi-worker contention or production concurrency; Phase 6 integration tests remain required.

## 10. Known limitations and explicit non-goals

- No webhook endpoint in Phase 2; provider-specific ingress controls belong to Phase 5.
- No real payment processing, card data, UPI credentials, or funds movement.
- Rate limiting does not replace authentication, authorization, idempotency, fraud detection, WAF, bot management, or provider controls.
- SQLite is suitable for local learning, not proof of production multi-instance concurrency.
- No claim of production readiness until all phases and deployment/security gates are complete.

## 11. Remaining project phases

| Phase | Scope | Dependency / status |
|---|---|---|
| 0 | Alembic migration foundation | Complete — PR #3 merged |
| 1 | Authentication, authorization, tenant isolation | Complete — PR #4 merged; browser E2E still outstanding |
| 2 | API rate limiting and abuse controls | Current phase |
| 3 | Durable append-only audit logging | After Phase 2 |
| 4 | Immutable double-entry ledger and reconciliation | After Phase 3; requires accounting domain review |
| 5 | Payment provider adapter and signed webhook verification | Depends on provider selection and Phases 3–4 |
| 6 | PostgreSQL concurrency and failure-injection tests | Final technical gate across prior phases |
| Deployment gate | Secrets, TLS, monitoring, backups/restore, rollback, security review, provider sandbox/compliance | Required before public/real use |

## 12. Change-control checklist

- [ ] Confirm current branch and clean base before every implementation batch.
- [ ] Record each new bug with severity, exact file/route, reproduction, and regression test.
- [ ] Fix only verified issues; avoid unrelated refactors.
- [ ] Add Alembic migration for schema changes; no startup schema creation.
- [ ] Run focused tests, full pytest, migration drift check, and frontend syntax check where relevant.
- [ ] Inspect final diff for tenant leaks, role bypass, transaction regressions, and secrets in logs.
- [ ] Update this file with commit SHA and actual CI evidence.
- [ ] Keep PR draft/open until final review; do not merge without explicit user approval.
