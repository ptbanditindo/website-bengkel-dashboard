"""Database engine, session factory, and initialization helpers.

Default database URL is ``sqlite:///./data/workshop.db`` (configurable via the
``DATABASE_URL`` environment variable so the backend can later switch to
PostgreSQL without rewriting business logic).

SQLite foreign keys are explicitly enabled on every connection.
"""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from . import models  # noqa: F401  (registers models on Base.metadata)

DEFAULT_DATABASE_URL = "sqlite:///./data/workshop.db"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_database_url() -> str:
    """Return the configured database URL (DATABASE_URL env or the default)."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def _ensure_sqlite_directory(db_url: str) -> None:
    """Create the parent directory of a SQLite database file if needed."""
    prefix = "sqlite:///"
    if not db_url.startswith(prefix):
        return
    raw = db_url[len(prefix):]
    parent = Path(raw).parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)


def _build_engine(db_url: str) -> Engine:
    connect_args = {}
    if db_url.startswith("sqlite"):
        # Allow cross-thread usage (Telegram handlers / future web API).
        connect_args["check_same_thread"] = False

    engine = create_engine(db_url, connect_args=connect_args, future=True)

    if db_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # Wait up to 5s for a busy SQLite database before raising
            # "database is locked" (helps when bot and UI access concurrently).
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def enable_wal(engine: Engine) -> None:
    """Switch a SQLite engine to WAL journal mode (persistent per database file).

    Deliberately NOT applied to the default engine during H8B, because it would
    modify ``data/workshop.db``. Call it explicitly on a temporary/controlled
    database when WAL is approved for the operational deployment.
    """
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")


engine = _build_engine(get_database_url())
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    """Yield a database session and always close it (FastAPI-style dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations(db_url: str | None = None) -> None:
    """Apply Alembic migrations — the official schema mechanism.

    Non-destructive: only applies pending migrations; never drops or resets.
    """
    url = db_url or get_database_url()
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)

    # migrations/env.py overrides sqlalchemy.url from DATABASE_URL; point it
    # at the target database for the duration of the upgrade.
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def init_db(db_url: str | None = None) -> None:
    """Ensure the data directory exists and apply Alembic migrations."""
    url = db_url or get_database_url()
    _ensure_sqlite_directory(url)
    run_migrations(url)
