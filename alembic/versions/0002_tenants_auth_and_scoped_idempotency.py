"""Add tenants, users, sessions, and tenant-scoped payment idempotency.

Revision ID: 0002_tenants_auth
Revises: 0001_initial_schema
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002_tenants_auth"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(sa.text(
        "INSERT INTO tenants (id, name, created_at) VALUES (1, 'Legacy demo workspace', CURRENT_TIMESTAMP)"
    ))
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(180), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)

    # Rebuild the table to remove the old global idempotency-key unique constraint.
    # Every existing row is retained and assigned to the explicit legacy tenant.
    op.create_table(
        "payments_new",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payment_id", sa.String(40), nullable=False),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("customer_email", sa.String(180), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("method", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", name="uq_payments_payment_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_payments_tenant_idempotency"),
    )
    op.execute(sa.text("""
        INSERT INTO payments_new (
            id, tenant_id, payment_id, customer_name, customer_email, amount_paise,
            currency, method, status, description, idempotency_key, created_at, refunded_at
        )
        SELECT id, 1, payment_id, customer_name, customer_email, amount_paise,
               currency, method, status, description, idempotency_key, created_at, refunded_at
        FROM payments
    """))
    op.drop_table("payments")
    op.rename_table("payments_new", "payments")
    op.create_index("ix_payments_id", "payments", ["id"])
    op.create_index("ix_payments_tenant_id", "payments", ["tenant_id"])
    op.create_index("ix_payments_payment_id", "payments", ["payment_id"], unique=True)


def downgrade() -> None:
    # Downgrade cannot safely preserve two tenants that reused an idempotency key.
    # Refuse rather than silently discard tenant boundaries or fail midway.
    bind = op.get_bind()
    duplicate = bind.execute(sa.text("""
        SELECT idempotency_key FROM payments
        WHERE idempotency_key IS NOT NULL
        GROUP BY idempotency_key HAVING COUNT(DISTINCT tenant_id) > 1 LIMIT 1
    """)).first()
    if duplicate:
        raise RuntimeError("Cannot downgrade: idempotency keys are reused across tenants.")
    op.create_table(
        "payments_old",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("payment_id", sa.String(40), nullable=False),
        sa.Column("customer_name", sa.String(120), nullable=False),
        sa.Column("customer_email", sa.String(180), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("method", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.execute(sa.text("""
        INSERT INTO payments_old (
            id, payment_id, customer_name, customer_email, amount_paise,
            currency, method, status, description, idempotency_key, created_at, refunded_at
        )
        SELECT id, payment_id, customer_name, customer_email, amount_paise,
               currency, method, status, description, idempotency_key, created_at, refunded_at
        FROM payments
    """))
    op.drop_table("payments")
    op.rename_table("payments_old", "payments")
    op.create_index("ix_payments_id", "payments", ["id"])
    op.create_index("ix_payments_payment_id", "payments", ["payment_id"], unique=True)
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")
