# Project Overview and Alembic Migration Guide

> **Who this guide is for:** someone opening this repository for the first time, a developer learning FastAPI and databases, or an engineer reviewing the database design.
>
> **Short version:** this project is a learning/demo payment application. PR #3 adds a controlled way to change its database structure without relying on the application to create tables automatically every time it starts.

---

## 1. What does this project do?

The Payment Processing System is a small full-stack web application.

A user can:
- Open a browser dashboard.
- Enter a customer's name, email, amount, and payment method.
- Create a **simulated** payment.
- See the transaction in a table.
- View summary numbers such as transaction count and successful payment value.
- Request a simulated refund.

The backend stores payment records in a database. The frontend talks to the backend using HTTP requests.

### Important: this is not a real payment gateway

The project does not contact a bank, UPI network, card network, Stripe, Razorpay, or another payment provider. It does not move money.

The current demo uses a simple rule to simulate a decline: amounts ending in .99 are declined. Other valid amounts are treated as successful by the demo.

Never enter real card numbers, CVVs, UPI PINs, or banking credentials. Do not expose this application publicly as a real payment service.

---

## 2. How the application works

Think of the application as three main parts:

1. **Frontend:** what a person sees and clicks in the browser.
2. **Backend/API:** receives requests, validates input, applies payment rules, and returns responses.
3. **Database:** stores payment records so they remain available after a request finishes.

### Request flow

~~~text
Person using the browser
          |
          v
HTML + CSS + JavaScript
          |
          | HTTP request (JSON)
          v
FastAPI routes (app/main.py)
          |
          +---- Pydantic validation (app/schemas.py)
          |
          +---- Payment business rules (app/services.py)
          |
          +---- SQLAlchemy session (app/database.py)
                         |
                         v
                  SQLite database
                    payment.db
~~~

Example: when someone creates a payment:

1. The browser collects the form values.
2. JavaScript sends a POST request to /api/payments.
3. FastAPI receives the request.
4. Pydantic checks that the values are valid.
5. The payment service applies the demo payment and idempotency rules.
6. SQLAlchemy writes the payment record to the database.
7. FastAPI returns the result as JSON.
8. The browser refreshes the dashboard and transaction list.

### Where to find each part

| File or folder | Responsibility | Beginner explanation |
|---|---|---|
| frontend/index.html | Page structure and form | What appears on the screen |
| frontend/styles.css | Visual styling and responsive layout | How the page looks |
| frontend/app.js | Browser requests and interactions | How buttons and forms work |
| app/main.py | FastAPI routes | The backend's entry points |
| app/schemas.py | Request validation | Checks incoming data |
| app/services.py | Payment rules and database operations | What the application does |
| app/models.py | SQLAlchemy table definitions | What a payment record looks like |
| app/database.py | Database engine, session, and shared ORM base | How Python talks to the database |
| app/config.py | Application configuration | Where settings such as the database URL come from |
| tests/ | Automated tests | Checks that important behavior still works |
| .github/workflows/tests.yml | GitHub Actions test workflow | Runs tests when code is pushed or a PR is opened |
| docs/PRODUCTION_READINESS_PLAN.md | Future engineering work | The ordered list of remaining production controls |

---

## 3. First understand the database

A database stores information in tables. A table is similar to a spreadsheet: it has columns and rows.

This project currently has a main table named payments.

A simplified example:

| id | payment_id | customer | amount_paise | status |
|---:|---|---|---:|---|
| 1 | pay_a123 | Alex | 125050 | succeeded |
| 2 | pay_b456 | Sam | 9999 | declined |

Each row represents one simulated payment.

Some important columns:
- id: internal database identifier.
- payment_id: identifier returned by the API.
- customer_name and customer_email: customer details.
- amount_paise: amount stored as an integer in paise, not a floating-point money value.
- currency: currently INR.
- status: for example, succeeded, declined, or refunded.
- idempotency_key: helps recognize a repeated create-payment request.
- created_at and refunded_at: timestamps.

The Python class Payment in app/models.py describes the table to SQLAlchemy. SQLAlchemy maps Python objects to database rows.

### What is a database schema?

A schema is the database's structure:
- Which tables exist.
- Which columns each table has.
- What type of data each column stores.
- Which columns may be empty.
- Which values must be unique.
- Which indexes and relationships exist.

For example, changing a customer email column from 100 characters to 180 characters is a schema change. Adding a users table is also a schema change.

Changing a button's colour is not a database schema change.

---

## 4. The problem PR #3 solves

### Before PR #3

The application used this kind of startup operation:

~~~python
Base.metadata.create_all(bind=engine)
~~~

In simple English, this tells SQLAlchemy:

> "Look at the tables described by my Python models. If a table is missing, create it."

That is convenient for a small first demo. It is not a complete database upgrade system.

**Important distinction:** create_all() can create missing tables, but it does not act like a versioned migration history. It does not safely describe and apply every change needed to transform an older database into a newer schema.

Imagine the application already has 10,000 payment rows. Later, a developer adds a new required column, a foreign key, or a new table. The Python model changes, but the existing database does not automatically become a carefully upgraded version of that model.

That creates a risk:
- The application code expects a column that the database does not have.
- A deployment works on a brand-new database but fails on an existing one.
- A manual schema change is forgotten or applied differently in two environments.
- A rushed fix could lose or damage existing data.

### After PR #3

PR #3 introduces **Alembic**, the database migration tool designed to work with SQLAlchemy.

Instead of asking the application to create tables whenever it starts, a developer creates a migration file that explicitly describes a database change.

The migration is then run as a deliberate operation:

~~~bash
alembic upgrade head
~~~

In simple English:

> "Bring this database forward to the latest migration version."

The application and database schema now have separate responsibilities:
- Application startup runs the application.
- Alembic commands change the database schema.
- Tests check that the migration history and SQLAlchemy models agree.

---

## 5. What is a migration? A simple analogy

Imagine a building.

- The database is the building.
- The existing tables are its rooms.
- The data is the furniture and everything inside those rooms.
- A migration is an approved renovation instruction.

You do not demolish the building every time you want to add a room. You plan the change, apply it, and check that the existing rooms and their contents remain safe.

A database migration does the same kind of controlled change.

For example:

- Version 1: create the payments table.
- Version 2: add a users table.
- Version 3: add a tenant_id column to payments.
- Version 4: add an audit-events table.

Each version is a recorded step. A database can report which migration version it has reached.

### What does "head" mean?

head means the latest migration revision in the repository's migration history.

It does not mean "the latest Python code" or "the latest payment row". It means the newest database migration version.

### What is the alembic_version table?

Alembic creates a small table named alembic_version. It records the revision identifier that has been applied to the database.

It is a migration-history marker, not a payment table.

---

## 6. What exactly did PR #3 change?

PR #3 is intentionally focused on the database migration foundation.

| Change | Why it matters |
|---|---|
| Added alembic.ini | Gives Alembic its configuration and migration folder location |
| Added alembic/env.py | Connects Alembic to the project's existing SQLAlchemy metadata and database URL |
| Added alembic/script.py.mako | Template used when generating future migration files |
| Added 0001_initial_schema.py | Describes the initial payments table and its indexes/constraints |
| Added alembic to requirements.txt | Installs the migration tool |
| Added DATABASE_URL configuration | Allows the application and migration command to target the configured database |
| Updated app/database.py | Uses SQLite-specific connection settings only when the URL is SQLite |
| Updated app/main.py | Removes automatic schema creation from FastAPI startup |
| Added tests/test_migrations.py | Checks a fresh upgrade and an existing-database baseline scenario |
| Updated README.md | Explains how to run and manage migrations |

### Why reuse the existing Base?

The project already has a shared SQLAlchemy declarative base in app/database.py.

Alembic uses that same Base.metadata. This avoids creating a second, separate description of the application's tables.

The model remains the application's Python-side table definition. The migration file is the recorded database operation. Tests compare them so they do not silently drift apart.

### Why remove automatic table creation from FastAPI startup?

A web server may start multiple times:
- During local development.
- When a process restarts after a crash.
- When a deployment starts new application instances.
- When multiple workers run.

A web server starting should not be the event that changes a production database schema.

With PR #3, the deployment process must explicitly run the migration before the application version that depends on it is started.

This makes the database change visible, reviewable, and testable.

---

## 7. Understand the migration files

### alembic.ini

This is the main Alembic configuration file. It tells Alembic where to find the migration scripts and provides a local SQLite fallback URL.

The environment variable DATABASE_URL takes precedence in the migration environment. This lets a deployment point migrations at its intended database without committing credentials to source control.

### alembic/env.py

This is the bridge between Alembic and the application.

It:
1. Loads the Alembic configuration.
2. Reads the configured database URL.
3. Imports the existing SQLAlchemy Base and models.
4. Supplies Base.metadata to Alembic.
5. Runs migrations in online or offline mode.

**Online mode** connects to a database and applies migrations.

**Offline mode** generates SQL using the configured dialect without opening a database connection.

### alembic/versions/0001_initial_schema.py

This is the first migration revision.

Its upgrade() function creates the current payments table, its primary key, unique constraints, and indexes.

Its downgrade() function reverses that revision. In this initial migration, reversal drops the payments table. That is destructive and can delete payment rows.

Do not run a downgrade against valuable data without a verified backup and a deliberate rollback plan.

### alembic/script.py.mako

This is a template. When a developer creates a new revision, Alembic uses it to generate the Python file containing upgrade() and downgrade().

It is not itself a migration that changes the database.

---

## 8. How to use migrations

Run these commands from the repository root, with the project's virtual environment activated and dependencies installed.

### A. Brand-new empty database

For a new database, run:

~~~bash
python -m pip install -r requirements.txt
alembic upgrade head
python -m uvicorn app.main:app --reload
~~~

The migration creates the tables and records the current revision. Then the application starts and uses those tables.

### B. Existing database from the old demo

This is a different situation.

The old demo automatically created its payments table. If that database already exists, running the initial migration as though the database were empty will try to create a table that is already there.

Do **not** blindly run alembic upgrade head against that old database.

Safe high-level process:

1. Stop the application so it is not writing to the database.
2. Make a backup of the database file.
3. Verify that the existing schema really matches the initial migration: column names and types, nullability, primary key, unique constraints, and indexes.
4. Only after that verification, record the existing schema as the initial revision.
5. Run the normal upgrade command.
6. Check that the application can read the existing payment rows.

The command to record the baseline is:

~~~bash
alembic stamp 0001_initial_schema
~~~

Then:

~~~bash
alembic upgrade head
~~~

**What does stamp mean?**

It writes the migration revision marker. It does not create the payments table, compare every column, repair missing indexes, or prove that the existing schema is correct.

That is why backup and schema verification must happen first. Stamping the wrong schema can make Alembic believe the database is at a revision it has not actually reached.

If you are unsure whether your local database is new or old, stop and inspect it before running either workflow.

### C. Useful inspection commands

~~~bash
alembic current
alembic history
alembic upgrade head
alembic check
~~~

- current: shows the revision recorded in the selected database.
- history: shows migration revisions in the repository.
- upgrade head: applies pending revisions up to the latest one.
- check: checks whether model metadata contains changes that are not represented by migration scripts.

### D. Creating a future migration

After changing a SQLAlchemy model, a developer can generate a candidate migration:

~~~bash
alembic revision --autogenerate -m "describe the schema change"
~~~

Then:
1. Open and review the generated migration.
2. Correct it manually if needed.
3. Check upgrade and downgrade behavior.
4. Add tests for data preservation and important constraints.
5. Run the migration against a disposable test database.
6. Review the PR before deployment.

**Never assume autogenerate is always correct.** It compares metadata and database state, but a human must review the generated operations, especially for renames, data transformations, constraints, and destructive changes.

---

## 9. How PR #3 is tested

The migration test file adds two important scenarios.

### Test 1: fresh database

It creates a temporary empty SQLite database and runs the migration.

It checks that:
- The payments table exists.
- The alembic_version table exists.
- The payment columns match the SQLAlchemy model's column names.
- Alembic's metadata check finds no unrecorded schema changes.

### Test 2: existing demo database

It creates a database using the existing SQLAlchemy model metadata, inserts a payment row, stamps the initial migration revision, and checks that the payment row remains readable afterwards.

This tests the baseline workflow and confirms that stamping itself does not delete the inserted payment row.

### What these tests do not prove

These are SQLite tests. They do not prove PostgreSQL behavior, production backup/restore, multi-worker concurrency, or every possible manually altered legacy schema.

The existing-database test builds its starting schema from the current SQLAlchemy metadata. It is a useful regression test, but it is not a substitute for checking a real copy of a user's old database before stamping it.

The CI run associated with the reviewed PR #3 commit reported **17 tests passed**. A passing test suite is evidence for the tested scenarios, not proof that the entire application is production-ready.

---

## 10. Project review: what is good and what is still missing?

### Good foundations already present

- FastAPI separates HTTP routes from payment service logic.
- Pydantic validates request fields at the API boundary.
- Decimal input is converted to integer paise for storage.
- Idempotency keys help avoid creating duplicate payments after a retry.
- Refund updates use a conditional database update.
- Dashboard totals are calculated with SQL aggregate queries.
- The frontend escapes customer-provided text before inserting it into transaction-table HTML.
- Automated tests cover payment validation, idempotency, refunds, and dashboard metrics.
- GitHub Actions runs the test suite.
- PR #3 introduces explicit, versioned schema migrations.

### Important limitations still present

| Area | Current position | Why it matters |
|---|---|---|
| Real payment provider | Not integrated | The application only simulates payment outcomes |
| Authentication | Not implemented | API routes do not establish who is making a request |
| Authorization | Not implemented | There are no verified user roles or permissions |
| Tenant isolation | Not implemented | Records are not scoped to separate customers/businesses |
| Rate limiting | Not implemented | Publicly reachable endpoints could be abused |
| Audit trail | Not implemented | There is no durable business record of who performed sensitive actions |
| Accounting ledger | Not implemented | A payment status row is not a full accounting system |
| Webhook verification | Not implemented | There are no provider callbacks or signature checks |
| Production database testing | Not implemented | Current tests use SQLite, not PostgreSQL |
| Monitoring and deployment controls | Incomplete | Production operations need alerting, secrets, backups, TLS, and recovery procedures |

### A frontend accuracy note

The dashboard includes a decorative activity chart in the HTML/SVG. It is not currently a historical time-series chart built from payment records. Treat it as visual presentation, not a source of actual daily transaction analytics.

### Important backend/security note

The current API has no authentication or tenant boundary. That is acceptable only within the clearly labelled local learning demo. Do not expose it publicly or use it with real customer/payment data.

See docs/PRODUCTION_READINESS_PLAN.md for the ordered work needed before considering a real deployment.

---

## 11. What should happen after PR #3?

The project roadmap intentionally works in small, reviewable phases:

1. **Alembic migrations** — safe, explicit database schema changes.
2. **Authentication, authorization, and tenant isolation** — establish who can access which records.
3. **Rate limiting** — reduce abuse and protect expensive/sensitive endpoints.
4. **Audit logging** — record important actions safely.
5. **Ledger and reconciliation** — account for financial events correctly.
6. **Provider integration and webhook verification** — connect to a real provider only after choosing one and following its official security rules.
7. **PostgreSQL concurrency and failure-injection tests** — verify behavior under real database contention and failures.

Each phase should have its own focused implementation, tests, and review. Do not combine all phases into one large PR.

---

## 12. Glossary: beginner to engineering terms

| Term | Plain-English meaning | Engineering meaning |
|---|---|---|
| API | A way for programs to talk | An interface exposing operations over HTTP or another protocol |
| Backend | The server-side part | Application services, routes, validation, and persistence |
| Database | Where records are stored | A persistent data store with constraints and transactions |
| ORM | A bridge between Python objects and database tables | Object-relational mapping; here, SQLAlchemy |
| Model | The code description of a stored object | ORM mapping and metadata for a database table |
| Schema | The shape of the database or request data | Columns, types, constraints, indexes, and validation contract |
| Migration | A recorded database change | A versioned, executable schema/data transformation |
| Revision | One migration version | A node in Alembic's migration history |
| Upgrade | Move the database forward | Apply pending migration operations |
| Downgrade | Move to an earlier version | Reverse a revision where a safe reverse operation exists |
| Stamp | Mark a revision as applied without running it | Update Alembic's version marker without executing migration operations |
| Metadata | SQLAlchemy's description of mapped tables | The MetaData object Alembic compares with the database |
| Constraint | A database rule | Primary key, unique, foreign key, check, or not-null enforcement |
| Index | A structure that helps find rows faster | A database access path, sometimes unique |
| Transaction | A group of database actions treated together | A commit/rollback boundary providing atomicity and related guarantees |
| CI | Automatic checks on code changes | Continuous Integration, here using GitHub Actions and pytest |
| Autogenerate | Let Alembic draft a migration | Metadata comparison that produces candidate operations for human review |

---

## 13. Final takeaway

PR #3 matters because database changes are part of application development. As this project grows, its database will need new tables, columns, constraints, and indexes. Those changes must be recorded and applied in a controlled way.

Before PR #3, the demo relied on SQLAlchemy's automatic table creation at application startup. After PR #3, the project has a migration history and an explicit command for applying schema changes.

That is a more reliable foundation for future work. It does **not** by itself add authentication, real payment processing, accounting, or production security.

**Remember the distinction:**
- SQLAlchemy models describe the application's database structure.
- Alembic migrations record how the database structure changes over time.
- The application handles requests and business rules.
- Tests provide evidence that the important behavior works.
- A production payment system requires additional security, accounting, provider, and operational controls.
