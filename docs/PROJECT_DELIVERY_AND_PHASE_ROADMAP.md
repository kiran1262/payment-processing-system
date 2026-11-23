

---

## 9. Expert QA findings — PR #4 baseline review

**Review scope:** PR #4 branch and the existing application baseline inspected during the Phase 1 kickoff review. This section records concrete defects and security gaps identified before the Phase 1 implementation. These are findings, not claims that fixes have already been applied.

**Review verdict:** Phase 1 implementation is not yet present in the reviewed PR diff. At the time of review, PR #4 contained the project roadmap document only. The existing main-branch test workflow completed successfully, but those tests do not demonstrate authentication or tenant isolation because those features are not implemented yet.

### Critical findings

#### QA-01 — Payment APIs have no authentication

**Severity:** Critical  
**Affected area:** `app/main.py` — dashboard, payment list, create, detail, and refund routes.

The payment endpoints do not require a verified user identity. A caller able to reach the API can access transaction/customer information, create simulated payments, and invoke refunds without proving who they are.

**Required correction:**
- Require a verified authenticated principal for every payment and tenant-management endpoint.
- Keep only explicitly public endpoints such as health, registration, and login unauthenticated.
- Return 401 for missing or invalid credentials.
- Add route-level tests proving unauthenticated requests cannot read or mutate payment data.

#### QA-02 — Payments have no tenant ownership or isolation

**Severity:** Critical  
**Affected area:** `app/models.py`, `app/services.py`, and payment routes in `app/main.py`.

Payment records do not belong to a tenant. List, detail, refund, and dashboard operations query across the entire database. Adding login alone would not fix this: one authenticated organization could still access another organization's records unless ownership is enforced in every query.

**Required correction:**
- Add tenant ownership and a foreign key to payment records.
- Add a data-preserving Alembic migration that assigns existing demo rows to an explicit legacy/demo tenant.
- Derive tenant identity from the verified server-side principal, never from client-supplied tenant IDs.
- Scope every payment read, update, refund, aggregate, and related service operation to the authenticated tenant.
- Return the same not-found response for a payment outside the tenant and an unknown payment.
- Add cross-tenant list/detail/refund/dashboard tests.

#### QA-03 — Idempotency keys are globally scoped

**Severity:** Critical  
**Affected area:** `app/models.py`, `app/services.py:create_payment`, and the initial Alembic schema.

The current idempotency key uniqueness and lookup are global. In a multi-tenant system, two unrelated tenants may legitimately use the same key. A global lookup/constraint can cause false conflicts and, if replay handling is not tenant-aware, risk returning a payment belonging to another tenant.

**Required correction:**
- Replace global key uniqueness with a composite uniqueness rule on tenant and idempotency key.
- Include tenant ID in the initial idempotency lookup.
- Include tenant ID in the concurrent-insert/IntegrityError recovery lookup.
- Verify that the same key works independently in two tenants, while same-tenant replay and payload-conflict behavior remain correct.

### Additional high/medium findings

#### QA-04 — Frontend retry can create duplicate payments after a lost response

**Severity:** High  
**Affected area:** `frontend/app.js` — payment form submission.

The browser generates a new random idempotency key for each submit. If the server commits the payment but the response is lost, a user retry sends a different key and may create a second payment.

**Required correction:**
- Keep the same idempotency key for retries of the same logical payment attempt.
- Rotate the key only when the user intentionally starts a new payment.
- Avoid silently clearing retry identity when the network result is uncertain.
- Test the server-committed/response-lost/retry scenario.

#### QA-05 — Static chart is presented as real payment activity

**Severity:** Medium  
**Affected area:** `frontend/index.html` — payment activity chart.

The chart contains hard-coded visual data rather than a time series derived from payment records. Its presentation can mislead users into believing the dashboard reports actual transaction activity.

**Required correction:**
- Replace the illustration with a properly aggregated, tenant-scoped API time series; or
- Clearly label the chart as illustrative demo artwork and do not present its values as live analytics.

#### QA-06 — UI copy overstates payment and security capabilities

**Severity:** Medium  
**Affected area:** `frontend/index.html`.

Claims and labels such as “Move money with confidence”, “SECURE PAYMENT”, “Verified”, “Protected environment”, and “All systems operational” imply real payment processing or security controls that this educational simulation does not provide.

**Required correction:**
- Use wording that consistently identifies the application as a simulated payment demo.
- Do not imply real money movement, provider authorization, security certification, or verification that has not occurred.
- Distinguish a basic application liveness response from database/provider readiness.

#### QA-07 — Health endpoint is not a readiness check

**Severity:** Medium  
**Affected area:** `app/main.py:/api/health`.

The endpoint returns a healthy response without checking database connectivity. That is acceptable as a simple liveness probe, but it cannot establish that the application is ready to serve database-backed requests.

**Required correction:**
- Keep the endpoint explicitly documented as liveness; and
- Add a separate readiness endpoint that performs a bounded database connectivity check if deployment or orchestration will rely on readiness status.
- Test both healthy and unavailable-database behavior without leaking internal exception details.

### Verification checklist for closing these findings

- [ ] Every protected endpoint rejects missing/invalid credentials.
- [ ] Registration, login, logout, expiry, revocation, and password verification are tested.
- [ ] Owner/member authorization is deny-by-default and tested for each privileged operation.
- [ ] Every payment query and mutation is tenant-scoped, including dashboard aggregates and idempotency recovery.
- [ ] Existing payment rows survive the tenant migration and are assigned to the documented legacy/demo tenant.
- [ ] Same idempotency key across different tenants is independent; same-tenant replay and payload conflict semantics remain correct.
- [ ] Retry after a committed request with a lost response does not create a duplicate payment.
- [ ] Dashboard chart is data-backed or explicitly labelled illustrative.
- [ ] UI copy accurately describes a simulated payment application.
- [ ] Liveness and readiness semantics are explicit and tested if readiness is added.
- [ ] Existing validation, payment, refund, and migration tests remain green.
- [ ] Full CI passes and a final route/service query review finds no missing tenant filters.

**Closure rule:** mark a QA item fixed only after the relevant code change is present, a regression test covers it, and the required checks pass. A review comment, documentation update, or green CI run for the documentation-only baseline is not evidence that the underlying defect has been fixed.
