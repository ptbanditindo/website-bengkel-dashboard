"""Shared pytest fixtures: an isolated in-memory SQLite database.

Tests never touch the production database (``./data/workshop.db``).
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure the project root is importable regardless of how pytest is invoked.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import database.models  # noqa: E402,F401  (register models on Base.metadata)
from database.base import Base  # noqa: E402

# ``tests/live`` contains manual live-test scripts (they send real Telegram/AI
# requests). They call ``load_dotenv()`` at module import, which would leak
# ``.env`` values (e.g. ``UI_ACCESS_TOKEN``) into the automated suite's
# environment. Ignore them during normal collection; run them explicitly via
# ``python tests/live/<script>.py`` when live testing is intended.
collect_ignore = ["live"]


@pytest.fixture()
def engine():
    """In-memory SQLite engine with foreign keys enabled."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    """A fresh session bound to the in-memory engine."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Service fixtures (Tahap B)
# ---------------------------------------------------------------------------
from services.vehicle_service import VehicleService  # noqa: E402
from services.service_record_service import ServiceRecordService  # noqa: E402


@pytest.fixture()
def vehicle_service(session):
    return VehicleService(session)


@pytest.fixture()
def service_record_service(session):
    return ServiceRecordService(session)



# WhatsApp CS fixtures (separate in-memory SQLite)
from whatsapp.models import WhatsAppBase  # noqa: E402


@pytest.fixture()
def wa_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    WhatsAppBase.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def wa_session(wa_engine):
    factory = sessionmaker(bind=wa_engine, autoflush=False, expire_on_commit=False)
    s = factory()
    yield s
    s.close()
