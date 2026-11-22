from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Payment

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "alembic.ini"


def migration_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_fresh_database_upgrades_to_head_and_matches_models(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    config = migration_config(database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "payments" in inspector.get_table_names()
        assert "alembic_version" in inspector.get_table_names()
        assert {column["name"] for column in inspector.get_columns("payments")} == {
            column.name for column in Payment.__table__.columns
        }
        # Fails if ORM metadata and the checked-in migration drift apart.
        command.check(config)
    finally:
        engine.dispose()


def test_existing_demo_schema_can_be_baselined_without_losing_payments(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'existing.db'}"
    engine = create_engine(database_url)
    payment = Payment(
        payment_id="pay_existing_123",
        customer_name="Existing Customer",
        customer_email="existing@example.com",
        amount_paise=125050,
        currency="INR",
        method="UPI",
        status="succeeded",
        description="Pre-migration payment",
        idempotency_key="existing-order-123",
    )

    try:
        # Simulate the schema produced by the application's previous create_all startup.
        Base.metadata.create_all(bind=engine)
        with Session(engine) as session:
            session.add(payment)
            session.commit()
            payment_id = payment.payment_id

        config = migration_config(database_url)
        command.stamp(config, "0001_initial_schema")
        command.upgrade(config, "head")
        command.check(config)

        with Session(engine) as session:
            preserved = session.scalar(
                select(Payment).where(Payment.payment_id == payment_id)
            )
            assert preserved is not None
            assert preserved.amount_paise == 125050
            assert preserved.customer_email == "existing@example.com"
    finally:
        engine.dispose()
