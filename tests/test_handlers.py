"""Tests for Telegram handlers (structured/manual flow)."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.orm import sessionmaker

import bot.handlers as handlers
from database.models import ServiceRecord, Vehicle


def make_update(user_id=123, text=None, callback_data=None):
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.callback_query = None
    if callback_data is not None:
        update.callback_query = MagicMock()
        update.callback_query.data = callback_data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
    return update


def make_context(args=None):
    context = MagicMock()
    context.args = args or []
    context.user_data = {}
    return context


@pytest.fixture(autouse=True)
def _authorized(monkeypatch):
    monkeypatch.setattr("bot.auth.is_authorized", lambda uid: True)


@pytest.fixture()
def db_factory(engine, monkeypatch):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(handlers, "SessionLocal", factory)
    return factory


@pytest.mark.asyncio
async def test_cmd_cari_finds_vehicle(db_factory):
    session = db_factory()
    session.add(Vehicle(nama_client="Budi", nopol="B1234ABC"))
    session.commit()
    session.close()

    update = make_update()
    context = make_context(args=["B", "1234", "ABC"])
    await handlers.cmd_cari(update, context)

    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.await_args[0][0]
    assert "Budi" in reply
    assert "B1234ABC" in reply


@pytest.mark.asyncio
async def test_cmd_cari_not_found(db_factory):
    update = make_update()
    context = make_context(args=["ZZZZZZ"])
    await handlers.cmd_cari(update, context)

    reply = update.message.reply_text.await_args[0][0]
    assert "tidak ditemukan" in reply


@pytest.mark.asyncio
async def test_cmd_cari_denies_unauthorized(db_factory, monkeypatch):
    monkeypatch.setattr("bot.auth.is_authorized", lambda uid: False)

    update = make_update()
    context = make_context(args=["B1234ABC"])
    await handlers.cmd_cari(update, context)

    reply = update.message.reply_text.await_args[0][0]
    assert "tidak memiliki akses" in reply


@pytest.mark.asyncio
async def test_register_conversation_saves_vehicle(db_factory):
    context = make_context()
    update = make_update()

    await handlers.cmd_daftar_entry(update, context)
    update.message.text = "Budi"
    await handlers.reg_name(update, context)
    update.message.text = "B 1234 ABC"
    await handlers.reg_plate(update, context)
    update.message.text = "081234567890"
    await handlers.reg_wa(update, context)
    update.message.text = "Toyota Avanza"
    await handlers.reg_type(update, context)
    update.message.text = "2020"
    await handlers.reg_year(update, context)
    update.message.text = "Jakarta"
    await handlers.reg_address(update, context)

    cb_update = make_update(callback_data="reg_save")
    await handlers.confirm_register_callback(cb_update, context)

    session = db_factory()
    vehicle = session.query(Vehicle).one()
    assert vehicle.nopol == "B1234ABC"
    assert vehicle.nama_client == "Budi"
    assert vehicle.tahun_mobil == 2020
    session.close()

    cb_update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_conversation_saves_record(db_factory):
    session = db_factory()
    session.add(Vehicle(nama_client="Budi", nopol="B1234ABC"))
    session.commit()
    session.close()

    context = make_context()
    update = make_update()

    await handlers.cmd_servis_entry(update, context)
    update.message.text = "B 1234 ABC"
    await handlers.svc_plate(update, context)
    update.message.text = "Pasang radiator|1|150000"
    await handlers.svc_jobs(update, context)
    update.message.text = "Radiator|1|850000"
    await handlers.svc_parts(update, context)
    update.message.text = "2027-01-14"
    await handlers.svc_warranty(update, context)
    update.message.text = "-"
    await handlers.svc_notes(update, context)

    cb_update = make_update(callback_data="svc_save")
    await handlers.confirm_service_callback(cb_update, context)

    session = db_factory()
    record = session.query(ServiceRecord).one()
    assert len(record.jobs) == 1
    assert len(record.parts) == 1
    assert record.biaya_jasa == Decimal("150000.00")
    assert record.total_part == Decimal("850000.00")
    assert record.total_servis == Decimal("1000000.00")
    assert record.garansi_sampai == date(2027, 1, 14)
    session.close()

    cb_update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_callback_handles_db_failure(db_factory, monkeypatch):
    session = db_factory()
    session.add(Vehicle(nama_client="Budi", nopol="B1234ABC"))
    session.commit()
    session.close()

    class FailingService:
        def __init__(self, session):
            pass

        def add_service_record(self, *args, **kwargs):
            raise RuntimeError("db down")

    monkeypatch.setattr(handlers, "ServiceRecordService", FailingService)

    context = make_context()
    context.user_data["svc_vehicle_id"] = 1
    context.user_data["svc_jobs"] = []
    context.user_data["svc_parts"] = []
    context.user_data["svc_garansi"] = None
    context.user_data["svc_catatan"] = None

    update = make_update(callback_data="svc_save")
    await handlers.confirm_service_callback(update, context)

    reply = update.callback_query.edit_message_text.await_args[0][0]
    assert "Data tidak tersimpan" in reply


@pytest.mark.asyncio
async def test_delete_callback_denies_unauthorized(db_factory, monkeypatch):
    monkeypatch.setattr("bot.auth.is_authorized", lambda uid: False)

    update = make_update(callback_data="confirm_delete_1")
    await handlers.confirm_delete_callback(update, make_context())

    update.callback_query.answer.assert_awaited_once()
    update.callback_query.edit_message_text.assert_not_awaited()


def test_build_application_registers_handlers(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:test")
    monkeypatch.setenv("BOT_DATA_FILE", str(tmp_path / "bot.pickle"))
    monkeypatch.setattr("bot.application.init_db", lambda: None)

    import bot.application as app

    application = app.build_application()
    assert application is not None
    assert len(application.handlers[0]) >= 5


def test_cancel_regex_matches_keywords():
    assert handlers.CANCEL_REGEX.match("batal") is not None
    assert handlers.CANCEL_REGEX.match("tidak jadi") is not None
    assert handlers.CANCEL_REGEX.match("CANCEL") is not None
    assert handlers.CANCEL_REGEX.match("Dhani") is None


@pytest.mark.asyncio
async def test_cancel_conversation_clears_and_ends():
    context = make_context()
    context.user_data["reg_name"] = "Dhani"
    update = make_update(text="tidak jadi")

    result = await handlers.cancel_conversation(update, context)

    assert result == handlers.ConversationHandler.END
    assert context.user_data == {}
    update.message.reply_text.assert_awaited_once()

