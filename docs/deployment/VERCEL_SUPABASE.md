# Vercel + Supabase deployment guide

This guide targets the educational payment simulation in this repository. It does not make the application production-ready and it must never be used to process real payments or store real card/UPI credentials.

## Deployment architecture

- **Vercel:** hosts the FastAPI application as a Python Function and serves the existing browser frontend through FastAPI.
- **Supabase PostgreSQL:** stores application records and shared rate-limit buckets.
- **Supabase shared transaction pooler:** handles short-lived serverless database connections.
- **Supabase pg_cron:** removes expired rate-limit buckets every ten minutes.

Keep the Vercel Function region close to the Supabase project region where your Vercel plan allows it. Cross-region database round trips add latency.

## 1. Create the Supabase database

1. Create a Supabase project and choose a region close to the intended Vercel Function region.
2. In the Supabase dashboard, open **Connect** and select **Transaction pooler**.
3. Copy the transaction-pooler connection string. It normally uses port **6543**.
4. Convert the URL scheme from `postgresql://` to `postgresql+psycopg://` so SQLAlchemy uses the installed Psycopg 3 driver.
5. URL-encode special characters in the database password before placing it in the URL.

The application engine detects Supabase's shared transaction pooler (port 6543), uses SQLAlchemy `NullPool`, requires TLS, and disables Psycopg automatic prepared statements. These settings are specific to the shared transaction pooler.

Do not use the Supabase service-role key or an anon key as `DATABASE_URL`. The application connects directly to PostgreSQL with the database username/password.

## 2. Apply Alembic migrations

Run migrations as a release/setup step, not during a Vercel request and not at application startup.

Prefer the Supabase **direct connection** URL for migrations. Direct connections may require IPv6 from the machine running Alembic. If that machine cannot reach the direct endpoint, use the Supabase **session pooler** connection for the migration command.

Set `MIGRATION_DATABASE_URL` to a SQLAlchemy Psycopg URL and run:

```bash
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m alembic check
```

The Alembic environment now gives `MIGRATION_DATABASE_URL` precedence over `DATABASE_URL`. Do not run migrations against the transaction pooler unless Supabase explicitly confirms the required DDL/session behavior for your project.

For a new Supabase project, `upgrade head` creates the schema. Do not stamp an empty database. The legacy-database stamping procedure in the main README applies only to an existing, verified pre-migration demo database.

## 3. Deploy to Vercel

1. Push this branch to GitHub.
2. In Vercel, import the repository `kiran1262/payment-processing-system`.
3. Set the project root directory to the repository root.
4. Let Vercel detect the Python/FastAPI application. The root `main.py` entrypoint exports the existing `app.main:app` application, so FastAPI receives the full request path (including the dashboard root and all API routes).
5. `vercel.json` explicitly includes `frontend/**` in the Python Function bundle because the application serves those files through `StaticFiles` and `FileResponse`.
6. Deploy a Preview first. Do not promote it to Production until the checklist below passes.

No separate frontend origin or CORS configuration is needed while the frontend and API are served by this same FastAPI application and Vercel deployment.

## 4. Configure Vercel environment variables

Add these values in **Project Settings → Environment Variables**. Set them for Preview and Production deliberately; do not commit secrets to Git.

| Variable | Required value |
|---|---|
| `APP_ENV` | `production` |
| `DATABASE_URL` | Supabase shared transaction-pooler URL, port 6543, using `postgresql+psycopg://` |
| `RATE_LIMIT_HASH_SECRET` | Unique high-entropy secret, at least 32 random bytes |
| `TRUSTED_PROXY_IPS` | Leave empty on Vercel; Vercel-specific client-IP resolution is used when `VERCEL=1` |

Generate a secret locally with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Set the generated value directly in Vercel's encrypted environment-variable settings. Never paste it into source control, a PR comment, or a public issue. Use a different secret for Preview and Production. Rotating this secret resets the effective rate-limit identity namespace, so rotate it deliberately.

Vercel provides the `VERCEL=1` system environment variable. The application then reads Vercel's platform-overwritten `X-Forwarded-For` header as one IP address. Vercel documents that it overwrites this header to prevent client IP spoofing. If the header is missing or malformed, public IP-based rate-limited endpoints fail closed with HTTP 503. Do not copy arbitrary client-supplied forwarding headers into this setting. If another proxy is placed in front of Vercel, the original client IP is not trusted unless your Vercel plan and proxy configuration explicitly support Trusted Proxy.

## 5. Schedule rate-limit cleanup in Supabase

Do not use the repository's systemd or Windows scheduler templates for Vercel.

After migrations create `public.rate_limit_buckets`:

1. Open the Supabase **SQL Editor**.
2. Review and run [`supabase/cron/purge_rate_limit_buckets.sql`](../../supabase/cron/purge_rate_limit_buckets.sql).
3. Open the Supabase Cron/Jobs view and verify that `payment-rate-limit-cleanup` is registered with schedule `*/10 * * * *`.
4. After the first run, inspect the job run history for errors.

The job deletes at most 1,000 expired rows per run. It rechecks expiry during deletion so a bucket refreshed concurrently is preserved. If cleanup falls behind, it catches up over subsequent runs.

## 6. Deployment verification checklist

- [ ] Preview deployment builds successfully and Vercel includes the `frontend/` assets.
- [ ] `/` serves the dashboard; `/static/app.js` and `/static/styles.css` return 200.
- [ ] `/api/health` returns 200.
- [ ] `/api/ready` returns 200 and confirms the Supabase database is reachable.
- [ ] `/docs` loads the FastAPI OpenAPI UI.
- [ ] Alembic reports the expected head revision in Supabase.
- [ ] Registration and login use distinct real client IP buckets on Vercel.
- [ ] Missing/malformed Vercel client-IP headers fail closed for public IP-based rate limits.
- [ ] Repeated login/payment requests return 429 with a positive integer `Retry-After`.
- [ ] Two separate Vercel Function instances share the same PostgreSQL rate-limit counters.
- [ ] Supabase Cron job runs successfully and removes expired buckets without deleting live buckets.
- [ ] Payment idempotency retry behavior and tenant/owner authorization pass browser E2E checks.
- [ ] Vercel and Supabase regions, connection latency, and PostgreSQL connection usage are measured.

## 7. Operational notes and limitations

- Vercel deployment does not automatically apply Alembic migrations. Keep schema changes as an explicit release step.
- Supabase's transaction pooler is intended for serverless short-lived connections. The application uses `NullPool`; do not add a large per-instance SQLAlchemy pool without measuring connection use.
- Transaction pooling does not preserve session state between transactions. The application must not rely on session-level settings, advisory locks, or temporary tables across requests.
- Rate-limit increments are committed independently from payment business transactions. A failed payment request can still consume its rate-limit budget.
- Supabase is now both the business database and rate-limit store. A database outage causes protected requests to fail closed.
- Fixed windows can permit a burst across adjacent window boundaries. A public production system needs a gateway/WAF policy, bot controls, MFA, monitoring, incident response, backups, restore drills, and a reviewed identity/session design.
- The browser still stores bearer tokens in `sessionStorage`; this is vulnerable to browser-side compromise such as XSS.
- This remains an educational simulation. It has no real payment provider, ledger/reconciliation, append-only audit system, signed webhook ingress, or PCI scope review.

## Official references

- [Vercel FastAPI deployment](https://vercel.com/docs/frameworks/backend/fastapi)
- [Vercel request headers](https://vercel.com/docs/headers/request-headers)
- [Vercel function configuration and includeFiles](https://vercel.com/docs/project-configuration/vercel-json)
- [Supabase database connection methods](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase connection pooling and limits](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits)
- [Supabase SQLAlchemy guidance](https://supabase.com/kb/troubleshooting/using-sqlalchemy-with-supabase-FUqebT)
