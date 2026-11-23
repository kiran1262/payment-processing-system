"""Add shared database-backed API rate-limit buckets.

Revision ID: 0003_rate_limit_buckets
Revises: 0002_tenants_auth
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003_rate_limit_buckets"
down_revision: Union[str, None] = "0002_tenants_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_buckets",
        sa.Column("bucket_key", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.Integer(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("bucket_key"),
    )
    op.create_index(
        "ix_rate_limit_buckets_expires_at",
        "rate_limit_buckets",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_rate_limit_buckets_expires_at", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
