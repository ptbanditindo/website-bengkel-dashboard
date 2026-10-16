"""Separate SQLite engine + session for the WhatsApp CS database."""

import os
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from whatsapp.models import WhatsAppBase, WaAgentSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_whatsapp_db_url() -> str:
    env = os.getenv("WHATSAPP_DB_URL")
    if env:
        return env
    path = PROJECT_ROOT / "data" / "whatsapp_cs.db"
    return "sqlite:///" + path.as_posix()


def _build_engine(url: str):
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args, future=True)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()
    return engine


engine = _build_engine(get_whatsapp_db_url())
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_whatsapp_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_columns() -> None:
    """Add columns introduced after the initial release (create_all is non-destructive)."""
    insp = inspect(engine)
    if "wa_contacts" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("wa_contacts")}
    if "owner_takeover_on" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE wa_contacts ADD COLUMN owner_takeover_on DATE"))


def init_whatsapp_db() -> None:
    """Create tables (non-destructive) and seed safe default settings."""
    url = get_whatsapp_db_url()
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///"):]
        parent = Path(raw).parent
        if str(parent) not in ("", "."):
            parent.mkdir(parents=True, exist_ok=True)
    WhatsAppBase.metadata.create_all(engine)
    _migrate_columns()
    db = SessionLocal()
    try:
        if db.get(WaAgentSettings, 1) is None:
            db.add(WaAgentSettings(id=1, nama_bengkel="AI Bengkel", alamat="", jam_operasional="Senin-Sabtu 08.00-17.00", maps_link="", agent_prompt="", default_delay_seconds=60, redirect_enabled=1))
            db.commit()
    finally:
        db.close()
