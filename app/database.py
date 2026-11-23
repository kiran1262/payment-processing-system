from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from .config import DATABASE_URL


def enable_sqlite_foreign_keys(engine):
    """Enable SQLite FK enforcement for every newly opened DBAPI connection."""
    if engine.dialect.name != "sqlite":
        return engine

    @event.listens_for(engine, "connect")
    def _set_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine


def create_application_engine(database_url: str):
    """Create an engine with connection behavior appropriate to the database host."""
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )
        return enable_sqlite_foreign_keys(engine)

    # Supabase's shared transaction pooler is intended for serverless workloads.
    # Keep one reusable client connection per warm Vercel instance, require TLS,
    # and disable psycopg automatic prepared statements (unsupported by the
    # shared transaction pooler). Pre-ping/recycle handle frozen warm instances.
    is_supabase_transaction_pooler = (
        url.port == 6543
        and bool(url.host)
        and url.host.endswith(".pooler.supabase.com")
    )
    if is_supabase_transaction_pooler:
        return create_engine(
            database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=10,
            pool_recycle=300,
            pool_pre_ping=True,
            connect_args={"sslmode": "require", "prepare_threshold": None},
        )

    return create_engine(database_url, pool_pre_ping=True)


engine = create_application_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
