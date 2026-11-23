# Phase 2 — Rate Limiting and Abuse Controls

> **Single source of truth for Phase 2 scope, implementation, QA evidence, deployment actions, and remaining work.**
>
> Repository: `kiran1262/payment-processing-system`  
> Base branch: `main`  
> Working branch: `feat/phase-2-rate-limiting-abuse-controls`  
> Pull request: [#5 — Phase 2: API rate limiting and abuse controls](https://github.com/kiran1262/payment-processing-system/pull/5)  
> Status: **Implementation and automated verification complete for this phase; PR remains draft. Deployment-specific proxy and scheduler activation are still operator tasks.**  
> Safety boundary: educational payment simulation only; no real funds, cards, UPI, or payment-provider integration.

---

## 1. Project purpose and safety boundary

This repository is an educational payment simulation built with FastAPI, SQLAlchemy, Alembic, SQLite for local development, and a browser frontend. It does not connect to a bank, card network, UPI provider, Stripe, or Razorpay and it does not move real money.

Phase 2 adds API abuse controls. It does **not** make the application production-ready. Do not expose the demo publicly or use real customer/payment credentials.

## 2. Verified project baseline

- PR #1: payment validation, idempotency, refunds, and dashboard query fixes — merged.
- PR #2: production-readiness roadmap and Ponytail skills — merged.
- PR #3: Alembic migration foundation — merged.
- PR #4: authentication, authorization, tenant isolation, legacy workspace bootstrap, SQLite foreign-key enforcement, owner-aware frontend controls, and dynamic profile identity — merged.
- Phase 1 CI evidence recorded in PR #4: 34 pytest tests passed. Browser E2E testing was not part of that CI run.
- Bearer tokens remain in browser `sessionStorage`; this remains exposed to XSS/browser compromise and is not a production session architecture.
- Phase 2 preserves tenant isolation, role checks, idempotency behavior, payment/refund semantics, and Alembic migration discipline.

## 3. Repository inventory and reuse map

| Area | Files | Phase 2 use |
|---|---|---|
| API boundary | `app/main.py` | Rate-limit dependencies at the HTTP boundary |
| Authentication | `app/auth.py` | Reuse verified user/tenant and owner dependencies |
| Database/config | `app/database.py`, `app/config.py` | Reuse the configured engine, session factory, and `DATABASE_URL` |
| ORM/migrations | `app/models.py`, `alembic/versions/*` | Rate-limit bucket model and migration 0003 |
| Limiter/proxy | `app/rate_limit.py`, `app/proxy.py` | Shared atomic counters, identity pseudonyms, trusted proxy policy |
| Maintenance | `app/maintenance.py`, `deploy/*` | Bounded expiry cleanup and scheduler templates |
| Frontend | `frontend/app.js` | Safe 429 retry guidance; preserve payment idempotency key |
| Tests/CI | `tests/test_rate_limiting.py`, `.github/workflows/tests.yml` | Deterministic tests, SQLite concurrency, PostgreSQL integration |
| Benchmark | `scripts/benchmark_rate_limit.py` | Measure limiter write contention and latency on target DB |

### Reuse-first and safety rules

1. Keep limiter identity server-derived; never trust request-body tenant/user identifiers.
2. Use a shared cross-worker store; process-local counters are not sufficient.
3. Keep policies separate by action and configurable.
4. Return HTTP 429 with a positive, bounded integer `Retry-After`.
5. Fail closed with a generic 503 if the limiter store cannot safely enforce a limit.
6. Do not log passwords, bearer tokens, request bodies, raw IPs, emails, or raw rate-limit keys.
7. Do not trust forwarded headers unless the immediate peer belongs to the explicit proxy allowlist.
8. Keep liveness/readiness endpoints exempt; protect them at the infrastructure layer if needed.
9. Do not weaken auth, tenant isolation, idempotency, refund, or migration behavior.
10. All schema changes must use Alembic; do not add startup `create_all`.

## 4. Phase 2 endpoint coverage and active policies

| Endpoint/action | Default limit | Window | Identity scope |
|---|---:|---:|---|
| Registration | 5 | 1 hour | Client IP |
| Login — IP | 60 | 15 minutes | Client IP |
| Login — network | 100 | 15 minutes | IPv4 /24 or IPv6 /64 prefix |
| Login — account | 10 | 15 minutes | HMAC of normalized email |
| Member creation | 10 | 1 hour | Authenticated user + tenant |
| Payment creation | 20 | 1 minute | Authenticated user + tenant |
| Refund | 5 | 1 minute | Authenticated user + tenant |
| Authenticated reads | 120 | 1 minute | Authenticated user + tenant |

The values are conservative demo defaults, not universal production recommendations. Tune them using real traffic and business requirements.

### Protected routes

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/tenant/members`
- `GET /api/dashboard`
- `GET /api/payments`
- `GET /api/payments/{payment_id}`
- `POST /api/payments`
- `POST /api/payments/{payment_id}/refund`

Health and readiness endpoints are intentionally exempt. Logout currently has no separate rate-limit policy; it is a low-risk follow-up unless abuse telemetry demonstrates a need.

Webhook ingress does not exist and must receive provider-specific controls in Phase 5.

## 5. Initial review findings — historical baseline

The original Phase 2 source audit identified missing limits on registration, login, payment creation, refunds, and reads; missing proxy trust policy; undefined shared-store behavior; missing cleanup; and frontend 429 handling gaps. Those findings motivated the implementation in this PR.

The initial audit also identified design risks that remain relevant:
- Fixed-window boundary bursts.
- IPv4/IPv6, NAT, and proxy identity handling.
- Account-scoped login throttling and its denial-of-service trade-off.
- Primary-database contention and outage coupling.
- Cleanup racing with active bucket refreshes.
- Clock synchronization across application instances.

The current implementation and the independent QA follow-up are described below. Historical findings must not be interpreted as current unimplemented work.

## 6. Selected implementation design

**Database-backed atomic fixed-window counters** are used in the configured shared SQL database. Dialect-native atomic upserts support SQLite and PostgreSQL. This avoids requiring Redis for the educational local setup while allowing workers sharing the same database to use the same counters.

Implemented behavior:

- Alembic revision `0003_rate_limit_buckets` creates the shared bucket table.
- SQLite and PostgreSQL upserts atomically increment counters.
- Stale requests cannot move a bucket window backwards; stale arrivals are conservatively accounted against the current stored window.
- Limiter increments commit independently before the business handler.
- HMAC-SHA256 pseudonyms are stored instead of raw caller identities.
- `RATE_LIMIT_HASH_SECRET` is mandatory when `APP_ENV=production`; the development fallback is not suitable for production.
- Missing ASGI peer identity fails closed with a generic 503; callers are not collapsed into a shared `unknown` bucket.
- Storage failures fail closed with a generic 503.
- Rate-limit responses include a bounded integer `Retry-After`.

### Login abuse controls

Login uses three independent HMAC-keyed scopes:
- IP address budget: limits repeated attempts from one address.
- Network-prefix budget: reduces simple IP rotation within one IPv4 /24 or IPv6 /64.
- Account budget: constrains attempts against one normalized account across multiple IPs.

Responses remain generic and raw account/IP values are not persisted. Account throttling can temporarily deny a legitimate user service after repeated attempts. A large botnet distributed across many networks can still evade these limits; MFA, breached-password checks, adaptive risk signals, bot controls, and monitoring remain necessary for a real service.

## 7. QA and automated verification

The independent QA report is [`PHASE_2_QA_REVIEW.md`](./PHASE_2_QA_REVIEW.md).

| QA finding | Resolution | Verification |
|---|---|---|
| Stale request can move window backwards | Monotonic atomic upsert and conservative stale-request accounting | Deterministic stale-window regression |
| Invalid zero/negative policy values fail during request handling | Validate policy configuration at startup | Subprocess configuration tests |
| Missing client peer creates shared unknown bucket | Fail closed with generic 503 | Missing-peer regression |
| Login IP-only throttling has NAT/distributed-spray limitations | IP + network-prefix + account budgets | Login scope, HMAC, and generic-response tests |
| SQLite-only tests do not prove PostgreSQL multi-worker behavior | File-backed SQLite concurrency plus PostgreSQL 16 multi-process CI | Four independent processes; 100 requests; exactly 50 allowed and all 100 increments retained |
| Cleanup is unbounded and lacks operational wiring | Bounded batches, maintenance command, systemd and Windows templates | Cleanup batch and live-bucket regression |
| Master documentation was stale/inconsistent | This record, QA report, README, and roadmap reconciled | Documentation cross-check |

### Latest verified automated evidence

Verified implementation and documentation CI evidence on PR head `cda50180767c86252bdaf3b85c69e596caf64828`:

- **61 pytest tests passed, 1 warning**.
- PostgreSQL 16 multi-process test passed: four processes, 100 requests, exactly 50 allowed, all 100 increments retained.
- PostgreSQL contention smoke benchmark: 100 requests, 8 workers; 732.9 requests/second, median 4.5 ms, p95 38.7 ms, max 58.6 ms on a GitHub-hosted runner.
- `node --check frontend/app.js` passed.
- Migration tests, including fresh upgrade and model drift checks, passed.
- The warning is the existing Starlette/httpx TestClient deprecation warning.

The benchmark is a CI smoke measurement, not a production capacity claim. Re-run against the actual staging/production database, schema, worker count, and network topology before choosing capacity limits.

## 8. Operational tooling and deployment actions

### Expired bucket cleanup

The bounded maintenance command is:

```bash
python -m app.maintenance purge-rate-limits --batch-size 1000
```

Deployment templates:
- `deploy/systemd/payment-rate-limit-cleanup.service`
- `deploy/systemd/payment-rate-limit-cleanup.timer`
- `deploy/windows/cleanup-rate-limits.ps1`

The systemd timer is configured for every ten minutes. Operators must adjust service user, working directory, virtualenv path, environment file, and database credentials before enabling it. On Windows, configure Task Scheduler to run the PowerShell script every ten minutes under an identity with the same application environment. The repository cannot activate a scheduler on a host it does not control.

### Trusted proxy configuration

- `TRUSTED_PROXY_IPS` accepts explicit IP addresses/CIDR networks; invalid and wildcard ranges are rejected.
- The default is empty, so forwarded headers are ignored.
- Configure only the actual immediate proxy addresses/CIDRs.
- Ensure the edge proxy sanitizes/replaces or safely appends `X-Forwarded-For`.
- Run Uvicorn with `--no-proxy-headers` so the application's allowlist remains the authority.
- Do not set `0.0.0.0/0` or `::/0`.

### Database contention and fixed-window trade-offs

- The primary database is also the limiter store. Limiter writes therefore compete with business writes and limiter availability is coupled to database availability.
- Run `python -m scripts.benchmark_rate_limit --workers 20 --requests 500` against a staging copy of the target database and actual worker topology.
- Consider Redis or gateway-managed limiting if p95 latency, lock waits, or write contention are material.
- Fixed windows can allow roughly 2N requests over a short interval spanning two adjacent windows. This behavior is documented and regression-tested. Strict burst smoothing requires a token bucket or sliding-window limiter at a trusted gateway/dedicated store.
- Keep application clocks synchronized across workers.

## 9. Remaining Phase 2 work

These are deployment/operational actions, not missing application implementation:

- [ ] Set `TRUSTED_PROXY_IPS` to the actual deployment proxy IPs/CIDRs and verify forwarded-header behavior end-to-end.
- [ ] Install and enable the systemd timer or Windows scheduled task on the actual deployment host.
- [ ] Run the contention benchmark against the actual staging database and worker topology; record p50/p95, lock waits, and resource usage.
- [ ] Tune rate-limit defaults against expected legitimate traffic and document the selected deployment values.
- [ ] Confirm production `RATE_LIMIT_HASH_SECRET` provisioning and rotation procedure.
- [ ] Verify monitoring/alerting for 429 rates, 503 limiter failures, cleanup failures, and unusual login patterns without logging raw identities.
- [ ] Complete browser E2E checks for login, payment retry/idempotency, 429 messaging, and owner-only actions before any production-like deployment.

Do not mark deployment readiness complete until these checks are performed in the actual target environment.

## 10. Known limitations and explicit non-goals

- Fixed-window boundaries permit short bursts across adjacent windows.
- Database-backed limiting adds write contention to the primary database.
- Account-level login throttling has a temporary account-denial trade-off.
- A distributed botnet can spread attempts across many networks.
- This is not a substitute for MFA, fraud detection, WAF/bot management, breached-password detection, or provider controls.
- No webhook endpoint, real payment provider, card data, UPI credentials, or funds movement is included.
- No claim of production readiness is made.

## 11. Remaining project phases

| Phase | Scope | Status / dependency |
|---|---|---|
| 0 | Alembic migration foundation | Complete — PR #3 merged |
| 1 | Authentication, authorization, tenant isolation | Complete — PR #4 merged; browser E2E remains a deployment-readiness check |
| 2 | API rate limiting and abuse controls | Implementation and CI verification complete in PR #5; deployment actions in section 9 remain |
| 3 | Durable append-only audit logging | Next implementation phase |
| 4 | Immutable double-entry ledger and reconciliation | After Phase 3; requires accounting-domain review |
| 5 | Payment provider adapter and signed webhook verification | Depends on provider selection and Phases 3–4 |
| 6 | Cross-phase PostgreSQL concurrency and failure-injection tests | Broader final technical gate; Phase 2 limiter concurrency is already tested |
| Deployment gate | Secrets, TLS, monitoring, backups/restore, rollback, security review, provider sandbox/compliance | Required before public/real use |

## 12. Change history and independent QA record

- 2026-11-23: Phase 2 source audit and initial atomic limiter implementation.
- 2026-11-23: Added migration 0003, route policies, 429/503 handling, frontend retry guidance, and initial tests (47 passed at that baseline).
- 2026-11-23: Independent QA identified seven issues; findings are recorded in `PHASE_2_QA_REVIEW.md`.
- 2026-11-23: Follow-up hardening added monotonic windows, startup config validation, missing-peer handling, trusted proxy support, IP/network/account login throttling, bounded cleanup and scheduler templates, SQLite concurrency tests, PostgreSQL 16 multi-process CI, and a contention benchmark.
- 2026-11-23: Verified PR head `cda50180767c86252bdaf3b85c69e596caf64828` passed CI: 61 passed, 1 warning; PostgreSQL multi-process test and contention smoke benchmark passed (732.9 req/s, median 4.5 ms, p95 38.7 ms, max 58.6 ms); frontend syntax passed.

The QA report records the original findings and the follow-up remediation evidence. It should be updated whenever new verification or deployment evidence is obtained.

## 13. Change-control checklist

- [x] Record initial findings with severity, failure scenario, and required regression coverage.
- [x] Fix verified Phase 2 limiter issues without changing payment/auth domain semantics.
- [x] Use Alembic for the new bucket table; no startup schema creation.
- [x] Add deterministic rate-limit, configuration, proxy, cleanup, and identity tests.
- [x] Run full pytest, migration drift checks, SQLite concurrency, PostgreSQL multi-process concurrency, PostgreSQL contention smoke benchmark, and frontend syntax check.
- [x] Update README, production-readiness roadmap, QA report, and PR description.
- [ ] Complete deployment-specific proxy/scheduler/secret/benchmark actions in section 9.
- [ ] Inspect final PR diff and confirm GitHub reports it mergeable before requesting review.
- [ ] Keep PR draft/open until final review; do not merge without explicit user approval.


## 14. Selected deployment target — Vercel + Supabase

The deployment target selected for this project is **Vercel + Supabase PostgreSQL**. The implementation and operator procedure are documented in [`docs/deployment/VERCEL_SUPABASE.md`](../deployment/VERCEL_SUPABASE.md).

Deployment-specific changes added on the Phase 2 branch:
- `main.py` exports the existing FastAPI application for Vercel's Python runtime.
- `vercel.json` explicitly includes `frontend/**` in the function bundle because FastAPI serves those assets.
- `app/database.py` detects Supabase's shared transaction pooler on port 6543 and uses SQLAlchemy `NullPool`, TLS, and disabled Psycopg automatic prepared statements.
- `app/proxy.py` and `app/main.py` use Vercel's documented platform-overwritten `X-Forwarded-For` client IP when `VERCEL=1`. Missing or malformed values fail closed for public IP-limited routes. Self-hosted proxy allowlisting remains unchanged.
- `alembic/env.py` accepts `MIGRATION_DATABASE_URL` so schema migrations can use a direct/session connection instead of the serverless transaction pooler.
- `supabase/cron/purge_rate_limit_buckets.sql` schedules an expiry cleanup of at most 1,000 rows every ten minutes using Supabase pg_cron.

### Operator-owned setup still required

- [ ] Create the Supabase project and choose the database region.
- [ ] Disable the Supabase Data API because the app uses direct PostgreSQL only; if it remains enabled, verify no `anon`/`authenticated` grants and appropriate RLS on application tables.
- [ ] Apply Alembic migrations using `MIGRATION_DATABASE_URL`.
- [ ] Configure Vercel `APP_ENV`, transaction-pooler `DATABASE_URL`, and unique high-entropy `RATE_LIMIT_HASH_SECRET`.
- [ ] Import the repository into Vercel and verify Preview deployment, frontend assets, API health/readiness, and docs.
- [ ] Run the Supabase pg_cron SQL script and verify successful job history.
- [ ] Complete browser E2E, cross-instance rate-limit, latency, connection-use, monitoring, backup/restore, and rollback checks.

No Supabase project, Vercel project, production credentials, migration, cron job, or live deployment has been created/configured by these repository changes. PR #5 remains draft/open and must not be merged without explicit approval.


### Latest Vercel/Supabase preparation CI evidence

The Vercel/Supabase code and regression tests passed on PR branch commit `aed28acf80445130cd25d8c5ca2b4ead52d91ed3` (workflow run [45131302189](https://github.com/kiran1262/payment-processing-system/actions/runs/45131302189)):
- **67 pytest tests passed, 1 warning**.
- Vercel client-IP parsing and middleware tests passed, including fail-closed malformed-header behavior.
- Supabase transaction-pooler engine selection and root FastAPI entrypoint tests passed.
- PostgreSQL 16 multi-process limiter test and contention smoke benchmark passed.
- Benchmark: 100 requests / 8 workers; 562.3 req/s, median 8.5 ms, p95 44.3 ms, max 52.8 ms on a GitHub-hosted runner.
- `node --check frontend/app.js` passed.

The benchmark is a CI smoke sample, not a production capacity guarantee. A later documentation-only change adds the Supabase Data API security instruction; the current branch's final CI run must also be green before this branch is considered fully verified.
