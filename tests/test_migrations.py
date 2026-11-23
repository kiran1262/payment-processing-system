from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from app.database import Base
from app.models import Payment

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "alembic.ini"

def migration_config(database_url: str, monkeypatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config

def test_fresh_database_upgrades_to_head_and_matches_models(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert {"payments", "tenants", "users", "auth_sessions", "alembic_version"} <= set(inspector.get_table_names())
        assert {c["name"] for c in inspector.get_columns("payments")} == {c.name for c in Payment.__table__.columns}
        command.check(config)
    finally:
        engine.dispose()

def test_existing_demo_payments_are_preserved_in_legacy_tenant(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'existing.db'}"
    config = migration_config(database_url, monkeypatch)
    command.upgrade(config, "0001_initial_schema")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO payments (
                    payment_id, customer_name, customer_email, amount_paise, currency,
                    method, status, description, idempotency_key, created_at, refunded_at
                ) VALUES (
                    'pay_existing_123', 'Existing Customer', 'existing@example.com',
                    125050, 'INR', 'UPI', 'succeeded', 'Pre-migration payment',
                    'existing-order-123', CURRENT_TIMESTAMP, NULL
                )
            """))
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as connection:
            row = connection.execute(text("""
                SELECT p.payment_id, p.amount_paise, p.tenant_id, t.name
                FROM payments p JOIN tenants t ON t.id = p.tenant_id
                WHERE p.payment_id = 'pay_existing_123'
            """)).one()
            assert row.payment_id == "pay_existing_123"
            assert row.amount_paise == 125050
            assert row.tenant_id == 1
            assert row.name == "Legacy demo workspace"
    finally:
        engine.dispose()
