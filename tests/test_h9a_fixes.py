"""Regression tests for H9A fixes: price '470k', relative dates, and draft state."""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.orm import sessionmaker

import bot.ai_handlers as ai_handlers
import bot.ai_runtime as ai_runtime
from ai.context import ConversationStore
from ai.orchestrator import AIOrchestrator
from ai.tools import PendingStore
from services import validation
from services.exceptions import ValidationError
from services.pricing import parse_money
from services.validation import coerce_date, coerce_datetime, normalize_warranty, validate_price


# ---------------------------------------------------------------------------
# Scenario A — price
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("470k", "470000.00"),
    ("470 K", "470000.00"),
    ("470rb", "470000.00"),
    ("470 ribu", "470000.00"),
    ("470.000", "470000.00"),
    ("470000", "470000.00"),
    ("Rp470.000", "470000.00"),
    ("Rp 470.000", "470000.00"),
])
def test_parse_money_indonesian_formats(text, expected):
    assert parse_money(text) == Decimal(expected)


def test_validate_price_470k():
    assert validate_price("470k") == Decimal("470000.00")


def test_validate_price_invalid():
    with pytest.raises(ValidationError):
        validate_price("abc")


def test_price_survives_date_fix(service_record_service, monkeypatch):
    # A date correction must not invalidate a valid price.
    monkeypatch.setattr(validation, "_today_wib", lambda: date(2026, 10, 15))
    rec = service_record_service.record_service_visit(
        nopol="D3414DSD",
        nama_client="Pak Dendi",
        waktu_service="hari ini",
        total_servis="470k",
        commit=False,
    )
    assert rec.total_servis == Decimal("470000.00")
    assert rec.waktu_service.date() == date(2026, 10, 15)


# ---------------------------------------------------------------------------
# Scenario B — date
# ---------------------------------------------------------------------------
@pytest.fixture()
def today_fixed(monkeypatch):
    monkeypatch.setattr(validation, "_today_wib", lambda: date(2026, 10, 15))
    return date(2026, 10, 15)


def test_coerce_date_hari_ini(today_fixed):
    assert coerce_date("hari ini") == date(2026, 10, 15)


def test_coerce_date_kemarin_besok(today_fixed):
    assert coerce_date("kemarin") == date(2026, 10, 14)
    assert coerce_date("besok") == date(2026, 10, 16)


def test_coerce_date_explicit_dd_mm_yyyy(today_fixed):
    assert coerce_date("15-10-2026") == date(2026, 10, 15)


def test_coerce_date_iso(today_fixed):
    assert coerce_date("2026-10-15") == date(2026, 10, 15)


def test_coerce_datetime_hari_ini(today_fixed):
    assert coerce_datetime("hari ini") == datetime(2026, 10, 15)


def test_coerce_date_relative_duration(today_fixed):
    assert coerce_date("3 hari") == date(2026, 10, 18)
    assert coerce_date("1 minggu") == date(2026, 10, 22)


def test_coerce_date_indonesian_month_names(today_fixed):
    assert coerce_date("2 agustus 2027") == date(2027, 8, 2)
    assert coerce_date("2 agustus") == date(2026, 8, 2)
    assert coerce_date("Agustus 2027") == date(2027, 8, 1)
    assert coerce_date("2 agu 2027") == date(2027, 8, 2)
    assert coerce_date("31 Desember 2026") == date(2026, 12, 31)


def test_normalize_warranty_rule(today_fixed):
    assert normalize_warranty(True, "2 agustus 2027") == (True, date(2027, 8, 2))
    assert normalize_warranty(False, None) == (False, None)
    assert normalize_warranty(None, None) == (None, None)
    assert normalize_warranty(None, "2027-08-02") == (True, date(2027, 8, 2))
    with pytest.raises(ValidationError):
        normalize_warranty(True, None)


def test_coerce_date_invalid(today_fixed):
    with pytest.raises(ValidationError):
        coerce_date("2026-02-30")
    with pytest.raises(ValidationError):
        coerce_date("32-13-2026")


# ---------------------------------------------------------------------------
# Scenario C — draft & state
# ---------------------------------------------------------------------------
def _make_callback_update(user_id, data):
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.callback_query = MagicMock()
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def _install_runtime(monkeypatch, engine):
    runtime = ai_runtime.AIRuntime()
    runtime.pending_store = PendingStore()
    runtime.orchestrator = AIOrchestrator(MagicMock(), runtime.pending_store)
    runtime.conversations = ConversationStore()
    monkeypatch.setattr(ai_handlers, "get_runtime", lambda: runtime)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(ai_handlers, "SessionLocal", factory)
    monkeypatch.setattr("bot.auth.is_authorized", lambda uid: True)
    return runtime


@pytest.mark.asyncio
async def test_confirm_resets_history(monkeypatch, engine):
    runtime = _install_runtime(monkeypatch, engine)
    runtime.conversations.get(123).add("user", "pesan lama")
    action = runtime.pending_store.add(
        123,
        [{"tool": "create_vehicle", "arguments": {"nama_client": "Budi", "nopol": "B 1234 ABC"}}],
        "ringkasan",
    )
    update = _make_callback_update(123, f"ai_confirm_{action.token}")

    await ai_handlers.ai_confirm_callback(update, MagicMock())

    # A finished transaction must not leak into the next message.
    assert runtime.conversations.get(123).as_list() == []


@pytest.mark.asyncio
async def test_cancel_resets_history(monkeypatch, engine):
    runtime = _install_runtime(monkeypatch, engine)
    runtime.conversations.get(123).add("user", "pesan lama")
    action = runtime.pending_store.add(
        123,
        [{"tool": "create_vehicle", "arguments": {"nopol": "B 1"}}],
        "ringkasan",
    )
    update = _make_callback_update(123, f"ai_cancel_{action.token}")

    await ai_handlers.ai_cancel_callback(update, MagicMock())

    assert runtime.conversations.get(123).as_list() == []


def test_execute_pending_keeps_draft_on_failure(engine):
    store = PendingStore()
    orch = AIOrchestrator(MagicMock(), store)
    action = store.add(
        123,
        [{"tool": "record_service_visit", "arguments": {"nopol": ""}}],
        "ringkasan",
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    with pytest.raises(ValidationError):
        orch.execute_pending(action.token, s, user_id=123)
    # Failed save keeps the draft for a retry instead of losing the input.
    assert store.get(action.token, 123) is not None
    s.close()

