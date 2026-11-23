# Phase 2 — Independent QA Review

> **Review type:** Static code review, acceptance-criteria audit, regression-test review, and documentation consistency review.  
> **Repository:** `kiran1262/payment-processing-system`  
> **PR:** [#5 — Phase 2: API rate limiting and abuse controls](https://github.com/kiran1262/payment-processing-system/pull/5)  
> **Original review snapshot:** `647c222980bcef8c1d899cacfc2ec8992e415880`  
> **Follow-up implementation verification:** 61 pytest tests passed, 1 warning; PostgreSQL 16 multi-process test, PostgreSQL contention smoke benchmark, and frontend syntax check passed.  
> **Current disposition:** All seven original QA findings have implementation or documentation remediation. Deployment-specific proxy/scheduler activation and target-environment benchmark remain operator-owned tasks. This is not production-readiness approval.

---

## 1. Executive summary

The original review identified seven issues in the Phase 2 rate limiter. The follow-up implementation addressed the code defects, added SQLite and PostgreSQL concurrency coverage, and added bounded cleanup tooling and deployment templates.

### Findings at a glance

| ID | Severity | Finding | Current status |
|---|---|---|---|
| P2-QA-01 | High | Older-window write could move a bucket backwards | Addressed; monotonic upsert and stale-window regression |
| P2-QA-02 | Medium | Invalid policy values could fail on request instead of startup | Addressed; startup validation and subprocess tests |
| P2-QA-03 | Medium | Missing peer address could collapse callers into one unknown bucket | Addressed; generic fail-closed 503 and regression |
| P2-QA-04 | Medium | IP-only login throttling had NAT and distributed-spray weaknesses | Improved; IP, network-prefix, and account budgets; botnet risk remains |
| P2-QA-05 | High | Atomicity and PostgreSQL multi-worker behavior were unverified | Addressed for Phase 2; SQLite threads and PostgreSQL 16 multi-process CI |
| P2-QA-06 | Medium | Cleanup was unbounded and not operationally wired | Addressed in code/templates; scheduler activation remains an operator task |
| P2-QA-07 | Low | Master documentation contained stale/inconsistent implementation status | Addressed; master record, QA report, README, and roadmap reconciled |

Severity describes risk to the educational application, not production certification.

## 2. Original findings and remediation evidence

### P2-QA-01 — Older window writes can move a bucket backwards

**Severity:** High  
**Original location:** `app/rate_limit.py`, `consume_rate_limit`

The original upsert assumed requests reached the database in the same order in which their timestamps were sampled. A delayed request from window N could overwrite a bucket already advanced to N+1, then cause a later request to reset the counter.

**Remediation:** The conflict update is monotonic. A stale arrival cannot replace a newer stored window; stale requests are accounted conservatively against the current stored window.

**Evidence:** Deterministic stale-window regression coverage is included in `tests/test_rate_limiting.py`.

### P2-QA-02 — Invalid policy configuration could fail at request time

**Severity:** Medium  
**Original location:** `app/rate_limit.py`, policy loading/enforcement

Zero or negative limits/windows could previously be parsed and only fail when a request used the policy.

**Remediation:** Policy configuration is validated during application startup/import. Invalid, zero, negative, and out-of-range values fail fast with an actionable configuration error.

**Evidence:** Subprocess tests cover invalid settings and valid overrides.

### P2-QA-03 — Missing client address created a shared unknown bucket

**Severity:** Medium  
**Original location:** `app/rate_limit.py`, IP identity dependency

Using a literal `ip:unknown` bucket could make unrelated callers share one budget when the ASGI peer address was absent.

**Remediation:** Missing required peer identity fails closed with a generic 503; it is not converted into a shared anonymous bucket.

**Evidence:** Missing-peer regression coverage is included in the rate-limit tests.

### P2-QA-04 — Login throttling needed NAT fairness and distributed-spray controls

**Severity:** Medium  
**Original location:** `app/rate_limit.py`, login dependencies

IP-only throttling can penalize users sharing an office, campus, household, or carrier NAT, while an attacker can distribute attempts across many IPs.

**Remediation:** Login now uses three HMAC-keyed budgets:
- IP: 60 attempts per 15 minutes.
- Network prefix: 100 attempts per 15 minutes per IPv4 /24 or IPv6 /64.
- Normalized account: 10 attempts per 15 minutes.

Generic throttling responses are used and raw email/IP identities are not persisted.

**Residual risk:** Account-level throttling can temporarily deny a legitimate user service. A large botnet spread across many networks can still evade the network budgets. MFA, breached-password checks, adaptive risk signals, bot controls, and monitoring remain necessary for a real service. This is not a permanent account-lockout mechanism.

**Evidence:** Tests cover IP/network/account buckets, HMAC pseudonyms, and generic behavior.

### P2-QA-05 — Atomicity and PostgreSQL multi-worker behavior were unverified

**Severity:** High  
**Original locations:** `tests/test_rate_limiting.py`, `.github/workflows/tests.yml`, `app/rate_limit.py`

SQLite in-memory tests alone could not prove multi-process behavior on PostgreSQL.

**Remediation:** Added file-backed SQLite concurrent-increment coverage and a PostgreSQL 16 CI service job that launches four independent Python processes against one shared bucket.

**Evidence:** 100 concurrent requests resulted in exactly 50 allowed requests at a configured limit of 50, while all 100 increments remained recorded. PostgreSQL integration passed in CI.

### P2-QA-06 — Cleanup was unbounded and had no scheduler tooling

**Severity:** Medium  
**Original location:** `app/rate_limit.py`, expired-bucket cleanup

A single unbounded delete could create database lock/WAL pressure; no command or scheduler template existed.

**Remediation:** Added bounded batch deletion with per-batch commits and an expiry recheck in the delete predicate. Added:
- `python -m app.maintenance purge-rate-limits --batch-size 1000`
- `deploy/systemd/payment-rate-limit-cleanup.service`
- `deploy/systemd/payment-rate-limit-cleanup.timer`
- `deploy/windows/cleanup-rate-limits.ps1`

**Evidence:** Cleanup tests cover batches and live buckets. Scheduler templates are in the branch.

**Operational residual:** The deployment owner must install/enable the scheduler on the actual host and provide the same database/secret environment as the application.

### P2-QA-07 — Master documentation was stale and inconsistent

**Severity:** Low  
**Original location:** `docs/phase-2/PHASE_2_REVIEW_AND_IMPLEMENTATION.md`

The original record mixed proposed and implemented designs, old test counts, old login policies, and outdated operational tasks.

**Remediation:** The master record now distinguishes implemented code, automated evidence, deployment actions, residual risks, and later project phases. README and production-readiness roadmap were reconciled.

**Evidence:** Documentation cross-check on the Phase 2 branch.

---

## 3. Route coverage review

| Route | Current protection | QA result |
|---|---|---|
| `POST /api/auth/register` | IP bucket | Present |
| `POST /api/auth/login` | IP + network-prefix + account buckets | Present |
| `GET /api/auth/me` | Authenticated read bucket | Present |
| `POST /api/auth/logout` | No separate rate-limit bucket | Low-priority follow-up; review if abuse telemetry justifies it |
| `POST /api/tenant/members` | Owner check + user/tenant bucket | Present |
| `GET /api/dashboard` | Authenticated read bucket | Present |
| `GET /api/payments` | Authenticated read bucket | Present |
| `GET /api/payments/{payment_id}` | Authenticated read bucket | Present |
| `POST /api/payments` | User/tenant create bucket | Present; idempotency remains separate |
| `POST /api/payments/{payment_id}/refund` | Owner check + user/tenant refund bucket | Present |
| `GET /api/health`, `GET /api/ready` | Exempt | Intentional |

## 4. Safeguards to preserve

- HMAC-SHA256 pseudonyms are stored instead of raw IP/user identities.
- Production startup requires `RATE_LIMIT_HASH_SECRET`.
- Forwarded headers are ignored unless the immediate peer is explicitly trusted.
- Authenticated buckets derive from verified user and tenant identity.
- Registration/login action budgets remain independent.
- Storage failure returns generic 503; 429 includes integer `Retry-After`.
- Frontend retry guidance does not discard the payment idempotency key.
- Rate-limit schema uses Alembic revision `0003_rate_limit_buckets`.
- Health and readiness endpoints remain exempt.

## 5. Latest automated verification

Latest verified implementation and documentation evidence on PR head `9dedbd4068de0061baed8c6a1864a740c727574d`:

- **61 pytest tests passed, 1 warning.**
- PostgreSQL 16 multi-process test: four independent processes, 100 requests, exactly 50 allowed, all 100 increments retained.
- PostgreSQL contention smoke benchmark: 100 requests, 8 workers; 768.7 requests/second, median 4.7 ms, p95 41.0 ms, max 53.0 ms on a GitHub-hosted runner.
- `node --check frontend/app.js` passed.
- Migration tests, including fresh upgrade and model drift checks, passed.
- The warning is the existing Starlette/httpx TestClient deprecation warning.

The benchmark is a CI smoke measurement, not a production capacity claim. Benchmark the actual target database and worker topology before deployment.

## 6. Remaining operational work

These tasks are not missing application code, but they are required before deployment readiness:

- [ ] Configure `TRUSTED_PROXY_IPS` with exact deployment proxy IPs/CIDRs and verify the proxy sanitizes forwarded headers.
- [ ] Install and enable the systemd timer or Windows scheduled task on the target host.
- [ ] Run the benchmark against the actual staging database and worker topology; record p50/p95, lock waits, and resource usage.
- [ ] Tune default policies for expected legitimate traffic.
- [ ] Provision and document rotation of production `RATE_LIMIT_HASH_SECRET`.
- [ ] Add operational alerting for 429 volume, limiter 503s, cleanup failures, and anomalous login attempts without logging raw identities.
- [ ] Complete browser E2E checks for login, payment idempotency retry, 429 messaging, and owner-only actions.

## 7. Residual risks and decision

- Fixed windows can allow approximately 2N requests across a short interval spanning adjacent windows. Strict burst smoothing needs token-bucket/sliding-window behavior at a trusted gateway or dedicated limiter.
- The primary database is the limiter store; benchmark actual write contention and offload to Redis/gateway if required.
- Application clock synchronization remains important across instances.
- Account throttling has a temporary denial-of-service trade-off.
- A large botnet distributed across many networks remains a risk.
- Logout has no separate rate-limit bucket; it is a low-priority review item.
- Webhook ingress is not implemented and remains Phase 5 work.

**QA decision:** The seven original Phase 2 findings have been remediated or explicitly converted into deployment-owned actions/residual risks. The automated Phase 2 acceptance evidence is green. PR #5 should remain draft until the final diff review and deployment-specific tasks are complete. This report does not grant production-readiness approval, and PR #5 must not be merged without explicit user approval.
