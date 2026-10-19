"""Regression tests for H-1B: safe fallback on main-database read failure."""

import asyncio

from sqlalchemy.exc import OperationalError

from whatsapp.agent import (
    DB_UNAVAILABLE_REPLY,
    DB_UNAVAILABLE_TOOL,
    WhatsAppAgent,
    run_restricted_tool,
)
from whatsapp.services import (
    ContactService,
    MatchingService,
    PriceService,
    QuestionService,
)


def _boom(*args, **kwargs):
    raise OperationalError("SELECT ...", None, None)


def test_context_db_failure_returns_safe_fallback(wa_session, session, monkeypatch):
    ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()

    monkeypatch.setattr(MatchingService, "match_by_wa_number", _boom)

    reply = asyncio.run(WhatsAppAgent().reply("0812-1", "mobil saya gimana?", wa_session, session))

    assert reply == DB_UNAVAILABLE_REPLY
    # no auto-escalation on DB failure
    assert QuestionService(wa_session).list() == []


def test_tool_db_failure_is_safe_and_no_leak(wa_session, session, monkeypatch):
    contact = ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()

    monkeypatch.setattr(MatchingService, "match_by_wa_number", _boom)
    assert run_restricted_tool("lookup_customer", {}, contact, wa_session, session) == DB_UNAVAILABLE_TOOL

    monkeypatch.setattr(PriceService, "check_stock", _boom)
    out = run_restricted_tool("check_stock", {"nama_part": "Oli"}, contact, wa_session, session)
    assert out == DB_UNAVAILABLE_TOOL
    assert "SELECT" not in out

    monkeypatch.setattr(PriceService, "part_price", _boom)
    assert run_restricted_tool("get_part_price", {"nama_part": "Oli"}, contact, wa_session, session) == DB_UNAVAILABLE_TOOL

    monkeypatch.setattr(PriceService, "jasa_price", _boom)
    assert run_restricted_tool("get_jasa_price", {"nama_jasa": "Servis"}, contact, wa_session, session) == DB_UNAVAILABLE_TOOL


def test_service_history_db_failure_no_internal_leak(wa_session, session, monkeypatch):
    contact = ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()

    monkeypatch.setattr(MatchingService, "service_history", _boom)
    out = run_restricted_tool("get_service_history", {"vehicle_id": 1}, contact, wa_session, session)

    assert out == DB_UNAVAILABLE_TOOL
    assert "SELECT" not in out
    assert "OperationalError" not in out


def test_service_history_invalid_vehicle_id(wa_session, session):
    contact = ContactService(wa_session).get_or_create("0812-1")
    out = run_restricted_tool("get_service_history", {"vehicle_id": "abc"}, contact, wa_session, session)
    assert out == "ID kendaraan tidak valid."


def test_db_failure_no_escalation_and_no_main_write(wa_session, session, monkeypatch):
    from database.models import Vehicle

    contact = ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()

    monkeypatch.setattr(PriceService, "check_stock", _boom)
    run_restricted_tool("check_stock", {"nama_part": "Oli"}, contact, wa_session, session)

    assert QuestionService(wa_session).list() == []
    assert len(session.query(Vehicle).all()) == 0
