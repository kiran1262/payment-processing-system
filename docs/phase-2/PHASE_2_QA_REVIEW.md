# Phase 2 — Independent QA Review

> **Review type:** Static code review, acceptance-criteria audit, test-coverage review, and documentation consistency review.  
> **Repository:** `kiran1262/payment-processing-system`  
> **PR:** [#5 — Phase 2: API rate limiting and abuse controls](https://github.com/kiran1262/payment-processing-system/pull/5)  
> **Reviewed branch head:** `647c222980bcef8c1d899cacfc2ec8992e415880`  
> **Review date:** 2026-11-23  
> **Disposition:** Initial findings have been addressed in a follow-up implementation batch. See the remediation status table below; do not mark Phase 2 complete until latest-head CI and deployment checks pass.

---

## 1. Executive summary

The Phase 2 implementation has a sound starting structure: route-level FastAPI dependencies, a shared SQL database counter table, SQLite/PostgreSQL dialect upserts, HMAC-pseudonymized bucket keys, 429 responses, fail-closed storage errors, and environment-configurable policies.

The previously reported CI result is **47 pytest tests passed, 1 warning**, with `node --check frontend/app.js` passing. This is not sufficient evidence for all acceptance criteria: concurrency is explicitly unchecked, PostgreSQL is not exercised, and the current fixed-window upsert has a stale-window race.

### Findings at a glance

| ID | Severity | Finding | Status |
|---|---|---|---|
| P2-QA-01 | High | A delayed request from an older window can move a bucket backwards and undermine the newer window's counter | Needs fix + regression test |
| P2-QA-02 | Medium | Zero/negative environment policy values cause an unhandled `ValueError` during requests | Needs fix + config tests |
| P2-QA-03 | Medium | Missing ASGI client address collapses all callers into one shared `unknown` IP bucket | Needs explicit safe behavior + test |
| P2-QA-04 | Medium | Login is only IP-throttled: NAT users can block each other, while distributed attempts can evade the limit | Risk decision / design improvement |
| P2-QA-05 | High | Concurrent upsert behavior and PostgreSQL behavior are not covered by automated tests | Verification blocker |
| P2-QA-06 | Medium | Cleanup is an unbounded delete on the primary database and has no operational scheduler/command | Operational hardening |
| P2-QA-07 | Low | Master document still contains stale/inconsistent proposal and verification wording | Documentation correction |

Severity is about the risk to the current educational application, not a claim that the demo is production-ready.

---

## 2. Detailed findings

### P2-QA-01 — Older window writes can move a bucket backwards

**Severity:** High  
**File:** `app/rate_limit.py`  
**Function:** `consume_rate_limit`

**Evidence**

The upsert uses the incoming request's `window_start` whenever the stored bucket window differs:

- `window_start`: if stored window equals incoming window, retain it; otherwise replace it with the incoming value.
- `request_count`: increment if equal; otherwise reset to 1.
- `expires_at`: always replace with the incoming window's expiry.

This assumes requests reach the database in the same order in which their timestamps were sampled.

**Failure scenario**

1. Worker A samples time in window N, then pauses before executing its upsert.
2. The clock crosses into window N+1.
3. Worker B writes window N+1 and starts its count.
4. Worker A resumes and writes its older window N.
5. A later request in N+1 sees a mismatch and resets the counter again.

The bucket can therefore move backwards and then reset again. This is possible around window boundaries with scheduling delays or clock skew. The current documentation acknowledges clock skew, but the SQL update itself does not protect against an older window overwriting a newer one.

**Required fix**

Make the stored window monotonic. Use the dialect's excluded/incoming row value in the conflict update so that an older incoming window cannot replace a newer stored window. Define how a stale request is counted (prefer conservative accounting against the current stored window rather than resetting it backwards). Keep the count, window, and expiry expressions consistent.

**Required regression tests**

- Deterministically simulate an old-window upsert after a new-window upsert.
- Assert the stored `window_start` never decreases.
- Assert a stale request cannot reset or increase the allowance available in the newer window.
- Run the same behavior against SQLite and PostgreSQL.

---

### P2-QA-02 — Invalid positive-policy configuration becomes an unhandled request error

**Severity:** Medium  
**File:** `app/rate_limit.py`  
**Functions:** `_policy`, `consume_rate_limit`, `_enforce`

**Evidence**

Environment values are parsed as integers in `_policy`. Positive-value validation happens later inside `consume_rate_limit`. A value such as `RATE_LIMIT_LOGIN_LIMIT=0` or a negative window parses successfully, then raises `ValueError` on every affected request. `_enforce` catches `SQLAlchemyError` and `RuntimeError`, but not this configuration error.

**Impact**

A deployment typo can produce HTTP 500 responses on the affected route rather than a clear startup/configuration failure. The service may start successfully while the endpoint is unusable.

**Required fix**

Validate every policy at application configuration time: limit and window must be positive integers, with documented upper bounds if operationally required. Fail startup with an actionable message naming the invalid environment variable. Do not convert a policy configuration error into a generic rate-limit storage 503.

**Required regression tests**

- Zero limit rejected during configuration.
- Negative limit rejected during configuration.
- Zero/negative window rejected during configuration.
- Valid override accepted.
- Error identifies the invalid setting without printing secrets.

---

### P2-QA-03 — Missing client address creates one global anonymous bucket

**Severity:** Medium  
**File:** `app/rate_limit.py`  
**Function:** `rate_limit_ip`

**Evidence**

When `request.client` is `None`, the code assigns the literal identity `ip:unknown`.

**Impact**

All requests without a socket peer share the same bucket for that action. A proxy, ASGI transport, or deployment configuration that omits the peer can cause unrelated users to throttle one another. This is an availability failure and can make behavior depend on infrastructure configuration.

**Required fix**

Do not silently map missing identity to a shared global identity. Choose and document a safe behavior: preferably fail closed with a generic 503 when the client identity is required but unavailable, or use a separately configured trusted edge identity. Never use a constant global bucket as a substitute for client identity.

**Required regression tests**

- Request with no `request.client` does not use the `unknown` bucket.
- Response follows the documented safe behavior.
- Normal IPv4 and IPv6 socket peers remain distinct.

---

### P2-QA-04 — Login IP-only throttling has both NAT and distributed-attack weaknesses

**Severity:** Medium  
**File:** `app/rate_limit.py`; `app/main.py` login dependency  
**Status:** Known design limitation; requires an explicit decision.

**Evidence**

The login route uses only `rate_limit_ip("login")`. The master record already acknowledges that distributed password spraying across many IPs remains possible.

**Additional impact**

- Users behind a shared office, campus, mobile-carrier, or household NAT share one IP budget and can block one another.
- An attacker with many source IPs can distribute attempts and avoid the per-IP threshold.

**Recommended design decision**

Evaluate a second account-scoped bucket using a keyed HMAC of a normalized email address. Do not reveal whether an account exists through different response codes or messages. Avoid a simple permanent account lockout: that would let attackers deny service to a known user. Consider combining IP and account signals with progressive delay, alerting, or a carefully bounded account bucket.

This is a policy/design finding, not a request to blindly add account lockout.

**Required tests if implemented**

- Same account from multiple IPs is detected by the account bucket.
- Different accounts behind one IP still respect the IP budget.
- Unknown and known accounts have indistinguishable externally observable throttling responses.
- Attacker cannot permanently lock out an account with a small number of attempts.

---

### P2-QA-05 — Atomicity and PostgreSQL behavior are not proven by the current test suite

**Severity:** High  
**Files:** `tests/test_rate_limiting.py`, `.github/workflows/tests.yml`, `app/rate_limit.py`

**Evidence**

- The master acceptance checklist leaves concurrent increments unchecked.
- Current rate-limit tests use SQLite in-memory test fixtures.
- The current CI job runs pytest and JavaScript syntax checking; it does not start PostgreSQL.
- The implementation supports SQLite and PostgreSQL upserts, but no PostgreSQL-specific integration evidence is recorded.

**Impact**

The most important claim of a shared limiter—concurrent requests cannot exceed the configured allowance through lost updates—has not been demonstrated under real concurrent requests or the second supported database dialect.

**Required verification**

- Add a deterministic concurrent-increment test against a file-backed SQLite database.
- Add a PostgreSQL service-backed integration job (or a separately tracked mandatory Phase 6 gate, with Phase 2 completion explicitly conditional on it).
- Launch more simultaneous requests than the configured limit and assert exactly the allowed count succeeds.
- Assert database bucket count and window state after the race.
- Include a multi-process test before claiming cross-worker production behavior.

The current SQL upsert is designed to be atomic, but design intent is not a substitute for a concurrency regression test.

---

### P2-QA-06 — Expired-bucket cleanup is unbounded and not operationally wired

**Severity:** Medium  
**File:** `app/rate_limit.py`  
**Function:** `purge_expired_rate_limit_buckets`

**Evidence**

The cleanup function issues one delete for every row whose `expires_at` is past and commits the entire operation. It is not exposed through a maintenance command or scheduled task.

**Impact**

If cleanup is run after a long period or the table grows substantially, one large delete can create write locks, transaction-log/WAL pressure, and latency on the same database used for business operations. If it is never scheduled, stale rows accumulate indefinitely.

**Required fix / operational decision**

- Add a documented maintenance command or deployment scheduler.
- Prefer bounded batches with a configurable batch size.
- Ensure cleanup cannot delete an active window.
- Record cleanup counts and failures without logging bucket identities.
- Document expected frequency and operational ownership.

**Required tests**

- Batch deletes no more than the configured batch size.
- Repeated runs eventually remove all expired rows.
- Live buckets remain untouched.
- Failure rolls back cleanly and can be retried.

---

### P2-QA-07 — Master document has stale and inconsistent review status

**Severity:** Low  
**File:** `docs/phase-2/PHASE_2_REVIEW_AND_IMPLEMENTATION.md`

**Evidence**

- Section 6 still describes the implementation direction as “pending final code review” even though the implementation is present.
- The proposal policy table omits the implemented member-creation limit.
- The implementation log records an older code/test SHA rather than distinguishing the code/test commit from the current PR head.
- The concurrency acceptance item is unchecked, but the top-level status does not call it out as a Phase 2 completion blocker strongly enough.

**Required fix**

Keep the master record as the source of truth. Separate:
1. Implemented and locally/CI verified.
2. Implemented but not concurrency/DB-dialect verified.
3. Operational deployment tasks.
4. Deferred design risks.

Do not mark Phase 2 complete while a required acceptance criterion remains unchecked.

---

## 3. Route coverage review

| Route | Current protection | QA result |
|---|---|---|
| `POST /api/auth/register` | IP bucket | Present |
| `POST /api/auth/login` | IP bucket | Present; NAT/distributed limitations above |
| `GET /api/auth/me` | Authenticated read bucket | Present |
| `POST /api/auth/logout` | No explicit rate-limit bucket | Low-priority review; assess whether repeated revocation lookups need a limit |
| `POST /api/tenant/members` | Owner check + user/tenant bucket | Present |
| `GET /api/dashboard` | Authenticated read bucket | Present |
| `GET /api/payments` | Authenticated read bucket | Present |
| `POST /api/payments` | User/tenant create bucket | Present; idempotency remains separate |
| `GET /api/payments/{payment_id}` | Authenticated read bucket | Present |
| `POST /api/payments/{payment_id}/refund` | Owner check + user/tenant refund bucket | Present |
| `GET /api/health`, `GET /api/ready` | Exempt | Intentional |

Route coverage is present for the primary Phase 2 scope. Logout throttling should be considered but is not currently a Phase 2 blocker unless abuse testing demonstrates a meaningful risk.

---

## 4. Existing safeguards that should be preserved

- HMAC-SHA256 pseudonyms are stored instead of raw IP/user identities.
- Production mode refuses to start without `RATE_LIMIT_HASH_SECRET`.
- Arbitrary `X-Forwarded-For` is not directly read by the limiter.
- Authenticated buckets derive from the verified user and tenant.
- Registration/login have independent action buckets.
- Rate-limit storage failure returns a generic 503 with `Retry-After`.
- 429 responses include integer `Retry-After`.
- Frontend shows retry guidance and the existing payment idempotency key remains a separate concern.
- Rate-limit schema is introduced through Alembic revision `0003_rate_limit_buckets`.
- Health and readiness endpoints are intentionally exempt.

Do not weaken these behaviors while addressing the findings.

---

## 5. Required fix and verification order

1. **Fix P2-QA-01** — monotonic window update and stale-window regression tests.
2. **Fix P2-QA-02** — validate all environment policy values before serving requests.
3. **Fix P2-QA-03** — define safe behavior for missing client address.
4. **Decide P2-QA-04** — document the login abuse policy and implement only a safe account signal if justified.
5. **Complete P2-QA-05** — concurrent tests and PostgreSQL verification, or explicitly retain it as a mandatory gate before Phase 2 completion.
6. **Fix P2-QA-06** — bounded cleanup and operational command/schedule documentation.
7. **Fix P2-QA-07** — reconcile the master document, README, and production roadmap.
8. Run focused tests, full pytest, migration drift check, frontend syntax check, SQLite concurrency tests, and PostgreSQL integration tests.
9. Review the final diff and update the PR description with actual latest-head CI evidence.

---

## 6. Current QA decision

**PR #5 should remain draft/open. Do not merge based only on the existing 47-test green CI run.**

The highest-priority code issue is the stale-window race in `consume_rate_limit`. The next priority is configuration validation. The concurrency/PostgreSQL acceptance gap must be closed or formally retained as a mandatory later gate with no production-readiness claim.

This review does not change application code. Findings are recorded for the next implementation pass.

## 7. Follow-up remediation status

| Finding | Remediation | Verification |
|---|---|---|
| P2-QA-01 stale-window race | Upsert keeps the stored window monotonic; stale requests are counted conservatively in the newest bucket. | Deterministic stale-window regression test. |
| P2-QA-02 invalid policy config | Action limits/windows are validated during module startup, including positive bounds and parse errors. | Subprocess tests for zero, negative, and non-integer values. |
| P2-QA-03 missing peer identity | Missing ASGI client identity returns generic 503 rather than a shared unknown bucket. | Dependency-level regression test. |
| P2-QA-04 distributed password spraying | Login uses a 60/15m IP budget and 10/15m HMAC account bucket; generic responses and no raw email persistence. | Login IP/network/account-budget and HMAC-digest tests. |
| P2-QA-05 concurrency/PostgreSQL | Added file-backed SQLite concurrent increment test and PostgreSQL 16 multi-process integration test in CI. | Must pass latest PR CI. |
| P2-QA-06 cleanup | Added bounded batch deletion and a maintenance command. | Batch cleanup regression; scheduler remains operator-configured. |
| P2-QA-07 documentation | Master record and README updated with policies, proxy, cleanup, benchmark, and boundary semantics. | Documentation review. |

### Operational completion notes

- Cleanup: systemd service/timer and Windows scheduled-task script are included; install/enable the matching template for the actual deployment host.
- Trusted proxy: set TRUSTED_PROXY_IPS to exact proxy addresses/CIDRs, ensure the proxy sanitizes/appends X-Forwarded-For, and run Uvicorn with --no-proxy-headers. Never trust all addresses.
- Database contention: run python -m scripts.benchmark_rate_limit --workers 20 --requests 500 against a staging database using the same DB engine and worker topology. Compare p50/p95 with the API latency budget; use a dedicated limiter if primary DB write contention is material.
- Fixed-window boundary burst: a limit of N can allow up to roughly 2N in a short interval spanning a boundary. This is tested and documented; strict burst smoothing requires token bucket/sliding window at a trusted gateway or a dedicated limiter.
- Password spraying: account-level HMAC throttling constrains distributed attempts but creates a bounded temporary lockout/denial-of-service trade-off. Generic responses reduce account enumeration. This is not a substitute for MFA, breached-password detection, bot controls, or anomaly monitoring.
- PostgreSQL multi-worker: CI starts PostgreSQL 16 and launches four independent Python processes against one shared bucket; exactly the configured number of requests must be allowed while all increments are retained.
