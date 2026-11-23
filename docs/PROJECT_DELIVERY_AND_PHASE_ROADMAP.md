# Payment Processing System — Project Journey, Security Plan, and Delivery Record

**Repository:** [kiran1262/payment-processing-system](https://github.com/kiran1262/payment-processing-system)  
**Purpose:** One project-level document for the end-to-end engineering process: why the work exists, what has been delivered, what each phase changes, how changes are verified, and what remains before any production claim.  
**Current project type:** Educational payment simulation. It does not move real money and is not a payment gateway.

> **Safety boundary:** Do not expose this demo publicly, enter real card/UPI/banking credentials, or use it for real customer/payment data. A passing test suite is not a production-readiness certification.

---

## 1. Executive summary

This repository is a full-stack learning project built around a FastAPI API, SQLAlchemy persistence, SQLite for local development, Alembic migrations, and a browser dashboard. Payment outcomes are simulated. The project is being improved in small, reviewable pull requests so that correctness, security, data integrity, and operational readiness are introduced in a deliberate order.

The engineering approach is:

1. Inspect the current implementation and its callers before changing code.
2. Reuse existing models, services, dependencies, and test fixtures.
3. Make one coherent change at a time.
4. Add a migration whenever the database schema changes.
5. Add tests for both expected behavior and security boundaries.
6. Review the complete diff and run the relevant test suite/CI.
7. Merge only after review and successful checks; merging remains the repository owner's decision.

## 2. Why this project needs staged improvements

A payment-shaped API has risks beyond ordinary CRUD. A caller must not be able to guess another customer's payment ID, reuse another tenant's idempotency key, trigger a refund without permission, or infer another tenant's transaction totals. Database changes must preserve existing records. Later, accounting and provider callbacks will need stronger transaction, replay, and reconciliation guarantees.

The project therefore separates the work into phases. Authentication is not considered complete unless authorization and tenant-scoped data access are enforced in the same change. Similarly, a webhook endpoint is not considered secure without provider-specific signature verification and replay protection.

## 3. Delivery history — what has already been completed

### PR #1 — Payment validation, idempotency, refunds, and dashboard queries

**Status:** Merged.

Delivered:
- Exact decimal amount validation and integer paise storage.
- Request validation, including bounded customer email length.
- Idempotency replay for matching requests and conflict responses for mismatched payloads.
- Database integrity-error handling around concurrent idempotency inserts.
- Conditional refund state transition.
- SQL aggregate dashboard metrics and bounded payment listing.
- Safer generic server errors with server-side exception logging.
- Automated tests, README updates, and CI coverage.

Why it matters: these changes strengthen the existing payment simulation's correctness and data handling before introducing more complex security and accounting concepts.

### PR #2 — Production readiness roadmap and Ponytail skills

**Status:** Merged.

Delivered:
- A phased production-readiness roadmap.
- Repository-specific implementation and review skills based on Ponytail v4.8.4.
- Third-party license attribution.

Why it matters: the project now has an agreed work order and a repeatable inspect-first, reuse-first, test-and-review workflow.

### PR #3 — Alembic database migration foundation

**Status:** Merged; the repository owner confirmed the latest CI passed.

Delivered:
- Alembic configuration, migration environment, and initial schema migration.
- Application and migration commands use the configured database URL.
- FastAPI startup no longer silently creates or changes the database schema.
- Migration tests cover a fresh database, ORM/schema drift, and baselining an existing demo database while preserving its payment row.
- A beginner-friendly project and migration guide.

Why it matters: future security and accounting features require controlled, repeatable schema evolution. Schema changes must be explicit and reviewable instead of being hidden inside application startup.

### Current baseline

The current main branch has a payment model and payment services, but the API does not yet have user authentication or tenant isolation. Payment list, detail, refund, dashboard, and idempotency lookups currently operate across the whole database. The browser dashboard also calls these APIs without credentials.

---

## 4. Full roadmap and why each phase exists

| Phase | Work | Why it is needed | Status |
|---|---|---|---|
| 0 | Alembic migration foundation | Safe, explicit schema evolution before adding security and accounting tables | **Completed in PR #3** |
| 1 | Authentication, authorization, tenant isolation | Establish trusted identity, permission checks, and strict ownership boundaries for every payment operation | **Started in PR #4** |
| 2 | API rate limiting and abuse controls | Reduce credential guessing, automated abuse, and excessive expensive requests; use shared enforcement across workers | Not started |
| 3 | Durable audit logging | Provide attributable records of sensitive actions without putting secrets in logs | Not started |
| 4 | Double-entry ledger and reconciliation | Separate payment lifecycle state from immutable accounting entries and reconcile against provider records | Not started |
| 5 | Provider integration and signed webhooks | Integrate a deliberately selected provider and safely verify, deduplicate, and process provider events | Not started |
| 6 | PostgreSQL concurrency and failure-injection tests | Validate transaction behavior under real database concurrency and injected failures | Not started |
| Cross-cutting | Secrets, TLS, deployment, monitoring, backups, restore drills, security review | Required operational controls that cannot be replaced by application code or unit tests | Not started |

### Phase 0 — Database migration foundation (completed)

**Main result:** database schema evolution is explicit and testable.

**Completion evidence:** PR #3 merged; Alembic initial migration and migration tests are in the repository; latest CI was confirmed passing by the repository owner.

### Phase 1 — Authentication, authorization, and tenant isolation (PR #4)

**Why these three concerns are one phase:** a tenant filter is not a security boundary if the caller can choose an arbitrary tenant ID. A login system is also incomplete if a logged-in user can still read or mutate another tenant's payments. Every protected operation must derive tenant identity from a verified principal and apply that tenant scope in its database query.

#### Intended security model

The following is the proposed minimal model for this educational application. Any change to the role policy or account onboarding behavior should be agreed before implementation is treated as final.

- **Tenant:** an isolated organization/account boundary.
- **User:** belongs to exactly one tenant and has a password hash, email, role, and active state.
- **Roles:** tenant `owner` and `member`. The owner manages tenant membership and can perform privileged actions such as refunds; a member receives only the explicitly granted operational permissions. Authorization is deny-by-default.
- **Registration:** public registration creates a new tenant and its first owner. It must not accept a caller-selected tenant ID.
- **Member onboarding:** an authenticated owner creates a member inside their own tenant. No public endpoint may create a member in an existing tenant.
- **Authentication:** login issues a cryptographically random opaque bearer token. Only a cryptographic hash of the token is stored. Sessions have a finite expiry and can be revoked at logout. Passwords are stored using a deliberately configured password-hashing scheme, never plaintext.
- **Protected API calls:** clients send `Authorization: Bearer <token>`. The server resolves the session, verifies expiry/revocation and active user status, and derives tenant and role from the database—not from request JSON, query parameters, or headers supplied as tenant claims.
- **Public endpoints:** health check, registration, and login only. All payment and tenant-management operations require authentication.
- **Error behavior:** missing/invalid/expired/revoked credentials return 401. A valid user lacking permission receives 403. A payment outside the caller's tenant should return the same not-found behavior as an unknown payment to avoid disclosing its existence.

#### Database changes expected

- Add tenant, user, and authentication-session tables with foreign keys and appropriate uniqueness constraints.
- Add a non-null tenant ownership relationship to payments.
- Add a migration that safely handles existing demo payment rows. Existing unowned rows must be assigned to a clearly named legacy/demo tenant; they must not be dropped or silently left globally visible.
- Replace global idempotency-key uniqueness with tenant-scoped uniqueness. A key may be reused by another tenant, but not to replay or conflict with a different payment inside the same tenant.
- Keep all schema changes in Alembic. Do not use application startup `create_all()` as a migration mechanism.

#### API behavior expected

| API operation | Authentication | Tenant / role rule |
|---|---|---|
| Health check | Public | No tenant data |
| Register tenant owner | Public | Creates a new tenant; tenant ID is server-generated |
| Login | Public | Returns a short-lived bearer session |
| Logout | Authenticated | Revokes only the current session |
| Create/list payments | Authenticated | Operates only in the caller's tenant |
| Payment detail | Authenticated | Tenant-scoped lookup |
| Refund | Authenticated | Owner-only unless a later explicit permission policy changes this |
| Dashboard | Authenticated | Aggregates only the caller's tenant |
| Create tenant member | Authenticated | Owner-only; member is created in the owner's tenant |

The browser dashboard must be updated to support registration/login and attach the bearer token to protected API calls. It must not put a tenant ID in browser storage and treat it as trusted identity. A browser-held bearer token is still exposed to browser compromise; this demo's authentication work does not replace a production session architecture, CSRF/XSS review, secure cookie strategy, or an identity provider.

#### Required tests

- Registration creates a tenant and owner; duplicate email is rejected safely.
- Login succeeds with a correct password and fails with an incorrect password.
- Missing, malformed, expired, and revoked bearer tokens are rejected.
- Logout revokes the current session.
- Role checks deny member-only attempts at owner-only actions.
- A user in tenant A cannot list, retrieve, refund, or affect dashboard totals for tenant B.
- A tenant A idempotency key cannot replay tenant B's payment; the same key can be independently used by another tenant.
- Existing payment rows survive the migration and are assigned to the legacy/demo tenant.
- Tenant IDs supplied by clients cannot override the authenticated tenant.
- The frontend handles unauthenticated state and does not silently send protected requests without credentials.

#### Phase 1 completion gate

Phase 1 is complete only when all protected routes enforce authentication, every payment query and write is tenant-scoped, role checks are explicit, migration tests preserve legacy data, the browser flow is compatible, and the complete automated test suite plus CI pass. A code review must inspect every route and service query for missing tenant filters.

### Phase 2 — Rate limiting and abuse controls

**Why:** authentication alone does not prevent password guessing or automated request floods.

Expected changes:
- Define limits for login/registration, payment creation, refunds, reads, and future webhook ingress.
- Prefer deployment gateway enforcement where available.
- If application-level enforcement is needed, use shared storage so multiple workers cannot each maintain an independent counter.
- Return 429 and an appropriate retry hint.
- Test burst behavior, reset windows, and shared consistency.

### Phase 3 — Audit logging

**Why:** sensitive operations need a durable actor, tenant, action, target, outcome, and timestamp trail.

Expected changes:
- Add append-only audit events with safe metadata and correlation IDs.
- Keep diagnostic logs separate from business audit records.
- Write state-change audit events in the same transaction when atomicity is required.
- Never log passwords, bearer tokens, card details, CVV, UPI PINs, or complete sensitive payloads.
- Test successful events and rollback behavior.

### Phase 4 — Ledger and reconciliation

**Why:** a mutable payment status is not an accounting ledger. Financial records require balanced, immutable entries and a way to compare internal records with provider settlement data.

Expected changes:
- Define accounts, journals, and debit/credit entries with currency.
- Enforce balanced postings and unique source references.
- Correct mistakes through reversals, not edits to posted entries.
- Define capture, settlement, fee, refund, and reversal rules with domain expertise.
- Reconcile provider reports and surface discrepancies.
- Do not invent real accounting entries for simulated historical payments.

### Phase 5 — Provider integration and webhook verification

**Why:** a client request must never be trusted to declare a real payment successful. Provider callbacks must be authenticated and safe against replay and duplicate delivery.

Expected changes:
- Select a provider deliberately and follow its official SDK and webhook documentation.
- Verify signatures over the exact raw request body.
- Validate timestamps/replay windows and secret rotation.
- Persist provider event IDs and deduplicate them independently from payment idempotency keys.
- Handle duplicate, delayed, and out-of-order events safely.
- Verify amount, currency, provider reference, and tenant/payment mapping before state transitions.
- Test invalid signatures, replay, duplicates, ordering, and provider timeouts.

### Phase 6 — PostgreSQL concurrency and failure-injection tests

**Why:** SQLite in-memory tests do not prove PostgreSQL locking and concurrent-writer behavior.

Expected changes:
- Keep fast SQLite tests for ordinary API behavior.
- Add PostgreSQL integration tests for concurrent payment creation, idempotency, refunds, webhook processing, unique constraints, and transaction rollback.
- Inject failures between writes and verify that partial financial state cannot commit.
- Assert final database state, not only HTTP status codes.

### Cross-cutting operational readiness

Before a real deployment, separately complete secrets management, TLS, least-privilege database credentials, monitoring/alerting, structured safe logs, backup and restore drills, dependency updates, security review, incident procedures, provider sandbox verification, and applicable compliance requirements. No phase in this roadmap by itself authorizes processing real payments.

---

## 5. PR #4 working agreement

**Branch:** `feat/phase-1-auth-tenant-isolation`  
**Target:** `main`  
**Scope:** Phase 1 only. Do not add rate limiting, audit events, ledger, provider integration, or unrelated refactoring to this PR.

Implementation order:
1. Confirm the role/onboarding policy and API contract.
2. Add tenant/user/session models and password/token handling.
3. Add Alembic migration, including legacy payment ownership and tenant-scoped idempotency uniqueness.
4. Add authentication and authorization dependencies.
5. Apply tenant-scoped queries to every payment operation and dashboard aggregation.
6. Add owner-only member onboarding and refund authorization.
7. Add frontend registration/login/session handling.
8. Add focused unit/API/migration tests.
9. Run the complete test suite and CI; inspect the final diff with the Ponytail review checklist.
10. Update this document's progress section with actual implementation and verification evidence before marking Phase 1 complete.

### Reuse-first implementation constraints

- Reuse `app/database.py:get_db`, `Base`, existing SQLAlchemy models, FastAPI dependency injection, current payment services, and the existing test-client dependency override.
- Keep business logic in service functions where appropriate; route handlers should remain thin.
- Do not trust client-supplied tenant IDs or roles.
- Do not store raw bearer tokens or plaintext passwords.
- Do not leak whether a payment exists in a different tenant.
- Keep existing amount validation, idempotency conflict behavior, conditional refund behavior, and migration drift checks.
- Add dependencies only when the standard library and existing stack are insufficient and the security trade-off is understood.
- Do not weaken tests to make CI green.
- Do not merge the PR automatically.

## 6. Progress and verification record

| Item | Status | Evidence / notes |
|---|---|---|
| PR #1 payment correctness baseline | Complete | Merged |
| PR #2 roadmap and Ponytail skills | Complete | Merged |
| PR #3 Alembic foundation | Complete | Merged; owner confirmed latest CI passed |
| PR #4 project-wide process document | Added to PR #4 branch | This document |
| PR #4 authentication implementation | In progress | Must be recorded after code is implemented |
| PR #4 tenant isolation | In progress | Must be verified route-by-route and with cross-tenant tests |
| PR #4 frontend authentication flow | In progress | Must be verified in browser/API tests |
| PR #4 full test suite and CI | Not yet verified | Do not claim success until checks actually pass |
| Phase 2–6 | Not started | Follow the roadmap above |

**Evidence rule:** update a status to complete only after the code exists, tests cover the behavior, the full relevant checks pass, and review has found no blocking issue. A branch or draft PR is not evidence that a phase is complete.

---

## 7. Glossary

- **Authentication:** proving which user is making a request.
- **Authorization:** deciding what that authenticated user is allowed to do.
- **Tenant:** an organization/account boundary used to isolate data.
- **Tenant isolation:** ensuring one tenant cannot read, change, count, or replay another tenant's records.
- **Bearer token:** a secret credential presented by the client; anyone holding it may be able to use it until it expires or is revoked.
- **Session revocation:** invalidating a previously issued token before its natural expiry.
- **Password hash:** a one-way, salted representation used to verify a password without storing the password itself.
- **Idempotency:** making safe retries return the original result instead of creating duplicate effects.
- **Migration:** a versioned, explicit database schema change.
- **Audit event:** a durable record of who performed an action, what happened, and when.
- **Ledger:** immutable accounting entries that record financial effects, distinct from a payment's current status.
- **Webhook:** an HTTP event sent by an external provider to notify the application of a change.
- **Reconciliation:** comparing internal records with an independent source, such as provider settlement reports.

---

## 8. Final project status

This repository is a progressively hardened educational payment simulation. PRs #1–#3 established payment correctness, a delivery roadmap, and explicit migrations. PR #4 is the start of the identity and tenant security boundary. The project must remain labelled as a simulation until a real provider, ledger, webhook verification, operational controls, compliance requirements, and independent security review are deliberately completed.
