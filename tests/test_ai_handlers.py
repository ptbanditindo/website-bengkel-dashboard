"""Tests for AI handlers (chat, confirmation, photo) with mocks."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.orm import sessionmaker

import bot.ai_handlers as ai_handlers
import bot.ai_runtime as ai_runtime
from ai.context import ConversationStore
from ai.errors import AIProviderError
from ai.orchestrator import AIOrchestrator
from ai.tools import PendingStore
from database.models import ServiceRecord, Vehicle


class FakeDeepSeek:
    configured = True

    def __init__(self, response):
        self._response = response
        self._used = False

    async def chat(self, messages, tools=None):
        # A real provider returns a fresh response each call; the fixture must
        # not repeat the same tool call forever (that would loop MAX iterations).
        if not self._used:
            self._used = True
            return self._response
        return {"content": "ok", "tool_calls": []}


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


@pytest.fixture(autouse=True)
def _authorized(monkeypatch):
    monkeypatch.setattr("bot.auth.is_authorized", lambda uid: True)


@pytest.fixture()
def db_factory(engine, monkeypatch):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(ai_handlers, "SessionLocal", factory)
    return factory


def _install_runtime(monkeypatch, deepseek=None):
    runtime = ai_runtime.AIRuntime()
    runtime.deepseek = deepseek if deepseek is not None else FakeDeepSeek({"content": "ok", "tool_calls": []})
    runtime.orchestrator = AIOrchestrator(runtime.deepseek, runtime.pending_store)
    runtime.conversations = ConversationStore()
    monkeypatch.setattr(ai_handlers, "get_runtime", lambda: runtime)
    return runtime


def _tool_call(name, arguments):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": arguments}}


@pytest.mark.asyncio
async def test_ai_message_handler_not_configured(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    runtime.deepseek = MagicMock()
    runtime.deepseek.configured = False

    update = make_update(text="halo")
    await ai_handlers.ai_message_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "belum dikonfigurasi" in reply


@pytest.mark.asyncio
async def test_ai_message_handler_shows_pending_buttons(monkeypatch, db_factory):
    runtime = _install_runtime(
        monkeypatch,
        FakeDeepSeek(
            {"content": "", "tool_calls": [
                _tool_call("create_vehicle", '{"nama_client": "Budi", "nopol": "B 1234 ABC"}')
            ]}
        ),
    )

    update = make_update(text="daftarkan mobil Budi plat B 1234 ABC")
    await ai_handlers.ai_message_handler(update, MagicMock())

    kwargs = update.message.reply_text.await_args.kwargs
    markup = kwargs["reply_markup"]
    button = markup.inline_keyboard[0][0]
    assert button.callback_data.startswith("ai_confirm_")
    # pending action stored
    assert len(runtime.pending_store._items) == 1


@pytest.mark.asyncio
async def test_ai_confirm_callback_executes(monkeypatch, db_factory):
    runtime = _install_runtime(
        monkeypatch,
        FakeDeepSeek(
            {"content": "", "tool_calls": [
                _tool_call("create_vehicle", '{"nama_client": "Budi", "nopol": "B 1234 ABC"}')
            ]}
        ),
    )

    update = make_update(text="daftarkan mobil Budi plat B 1234 ABC")
    await ai_handlers.ai_message_handler(update, MagicMock())

    token = next(iter(runtime.pending_store._items))
    cb_update = make_update(callback_data=f"ai_confirm_{token}")
    await ai_handlers.ai_confirm_callback(cb_update, MagicMock())

    reply = cb_update.callback_query.edit_message_text.await_args[0][0]
    assert "berhasil" in reply

    session = db_factory()
    assert session.query(Vehicle).count() == 1
    session.close()
    # token consumed
    assert len(runtime.pending_store._items) == 0


@pytest.mark.asyncio
async def test_ai_cancel_callback_discards(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    action = runtime.pending_store.add(
        123, [{"tool": "create_vehicle", "arguments": {"nopol": "B1234ABC"}}], "summary"
    )

    cb_update = make_update(callback_data=f"ai_cancel_{action.token}")
    await ai_handlers.ai_cancel_callback(cb_update, MagicMock())

    assert len(runtime.pending_store._items) == 0
    cb_update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_ai_photo_handler_not_configured(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    runtime.gemini = MagicMock()
    runtime.gemini.configured = False

    update = make_update()
    await ai_handlers.ai_photo_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "belum tersedia" in reply


@pytest.mark.asyncio
async def test_ai_message_handler_rejects_long_text(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)

    update = make_update(text="x" * 5000)
    await ai_handlers.ai_message_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "terlalu panjang" in reply


@pytest.mark.asyncio
async def test_ai_photo_handler_rejects_large_photo(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    runtime.gemini = MagicMock()
    runtime.gemini.configured = True

    update = make_update()
    photo = MagicMock()
    photo.file_size = 10 * 1024 * 1024  # 10 MB
    update.message.photo = [photo]

    await ai_handlers.ai_photo_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "terlalu besar" in reply


@pytest.mark.asyncio
async def test_ai_photo_handler_rejects_oversized_download(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    runtime.gemini = MagicMock()
    runtime.gemini.configured = True

    update = make_update()
    photo = MagicMock()
    photo.file_size = 1024  # small metadata, but the actual download is large
    file = MagicMock()
    file.download_as_bytearray = AsyncMock(return_value=b"\xff\xd8\xff" + b"x" * (6 * 1024 * 1024))
    photo.get_file = AsyncMock(return_value=file)
    update.message.photo = [photo]

    await ai_handlers.ai_photo_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "terlalu besar" in reply


@pytest.mark.asyncio
async def test_ai_photo_handler_rejects_non_jpeg(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    runtime.gemini = MagicMock()
    runtime.gemini.configured = True

    update = make_update()
    photo = MagicMock()
    photo.file_size = 1024
    file = MagicMock()
    file.download_as_bytearray = AsyncMock(return_value=b"not-a-jpeg-data")
    photo.get_file = AsyncMock(return_value=file)
    update.message.photo = [photo]

    await ai_handlers.ai_photo_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "tidak didukung" in reply


# ---------------------------------------------------------------------------
# H6B: handler-level integration tests (mock Telegram update/context + mock
# provider + isolated DB) — exercising the real handler path, not just services.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_message_handler_text_response(monkeypatch, db_factory):
    _install_runtime(monkeypatch, FakeDeepSeek({"content": "Halo! Ada yang bisa dibantu?", "tool_calls": []}))
    update = make_update(text="halo")
    await ai_handlers.ai_message_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "Halo" in reply
    assert "reply_markup" not in update.message.reply_text.await_args.kwargs


@pytest.mark.asyncio
async def test_ai_message_handler_denies_unauthorized(monkeypatch, db_factory):
    _install_runtime(monkeypatch)
    monkeypatch.setattr("bot.auth.is_authorized", lambda uid: False)
    update = make_update(text="catat servis")
    await ai_handlers.ai_message_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "tidak memiliki akses" in reply


@pytest.mark.asyncio
async def test_ai_confirm_record_service_visit_creates_vehicle_and_record(monkeypatch, db_factory):
    runtime = _install_runtime(
        monkeypatch,
        FakeDeepSeek(
            {"content": "", "tool_calls": [
                _tool_call(
                    "record_service_visit",
                    '{"nopol": "B 3413 FED", "nama_client": "Dhani", "total": "600rb", '
                    '"jobs": [{"deskripsi": "ganti radiator"}]}',
                )
            ]}
        ),
    )
    update = make_update(text="catat servis Dhani B 3413 FED ganti radiator total 600rb")
    await ai_handlers.ai_message_handler(update, MagicMock())

    token = next(iter(runtime.pending_store._items))

    # Nothing persisted before confirmation.
    session = db_factory()
    assert session.query(Vehicle).count() == 0
    assert session.query(ServiceRecord).count() == 0
    session.close()

    cb = make_update(callback_data=f"ai_confirm_{token}")
    await ai_handlers.ai_confirm_callback(cb, MagicMock())

    session = db_factory()
    assert session.query(Vehicle).count() == 1
    assert session.query(ServiceRecord).count() == 1
    record = session.query(ServiceRecord).one()
    assert record.total_servis == Decimal("600000.00")
    session.close()


@pytest.mark.asyncio
async def test_ai_cancel_no_db_change(monkeypatch, db_factory):
    runtime = _install_runtime(
        monkeypatch,
        FakeDeepSeek({"content": "", "tool_calls": [
            _tool_call("create_vehicle", '{"nama_client": "Budi", "nopol": "B 1234 ABC"}')
        ]}),
    )
    update = make_update(text="daftarkan mobil Budi plat B 1234 ABC")
    await ai_handlers.ai_message_handler(update, MagicMock())

    token = next(iter(runtime.pending_store._items))
    cb = make_update(callback_data=f"ai_cancel_{token}")
    await ai_handlers.ai_cancel_callback(cb, MagicMock())

    session = db_factory()
    assert session.query(Vehicle).count() == 0
    session.close()
    assert len(runtime.pending_store._items) == 0


@pytest.mark.asyncio
async def test_ai_confirm_rejects_reused_token(monkeypatch, db_factory):
    runtime = _install_runtime(
        monkeypatch,
        FakeDeepSeek({"content": "", "tool_calls": [
            _tool_call("create_vehicle", '{"nama_client": "Budi", "nopol": "B 1234 ABC"}')
        ]}),
    )
    update = make_update(text="daftarkan mobil Budi plat B 1234 ABC")
    await ai_handlers.ai_message_handler(update, MagicMock())

    token = next(iter(runtime.pending_store._items))
    await ai_handlers.ai_confirm_callback(make_update(callback_data=f"ai_confirm_{token}"), MagicMock())
    cb2 = make_update(callback_data=f"ai_confirm_{token}")
    await ai_handlers.ai_confirm_callback(cb2, MagicMock())

    reply = cb2.callback_query.edit_message_text.await_args[0][0]
    assert "tidak valid" in reply
    session = db_factory()
    assert session.query(Vehicle).count() == 1  # no duplicate
    session.close()


@pytest.mark.asyncio
async def test_ai_confirm_rejects_other_user(monkeypatch, db_factory):
    runtime = _install_runtime(
        monkeypatch,
        FakeDeepSeek({"content": "", "tool_calls": [
            _tool_call("create_vehicle", '{"nama_client": "Budi", "nopol": "B 1234 ABC"}')
        ]}),
    )
    update = make_update(user_id=123, text="daftarkan mobil Budi plat B 1234 ABC")
    await ai_handlers.ai_message_handler(update, MagicMock())

    token = next(iter(runtime.pending_store._items))
    cb = make_update(user_id=999, callback_data=f"ai_confirm_{token}")
    await ai_handlers.ai_confirm_callback(cb, MagicMock())

    reply = cb.callback_query.edit_message_text.await_args[0][0]
    assert "tidak valid" in reply
    session = db_factory()
    assert session.query(Vehicle).count() == 0  # no mutation
    session.close()


@pytest.mark.asyncio
async def test_ai_confirm_rejects_invalid_token(monkeypatch, db_factory):
    _install_runtime(monkeypatch)
    cb = make_update(callback_data="ai_confirm_")
    await ai_handlers.ai_confirm_callback(cb, MagicMock())

    reply = cb.callback_query.edit_message_text.await_args[0][0]
    assert "tidak valid" in reply


@pytest.mark.asyncio
async def test_ai_message_handler_clarification_no_pending(monkeypatch, db_factory):
    runtime = _install_runtime(
        monkeypatch,
        FakeDeepSeek({"content": "Plat nomor kendaraan berapa ya?", "tool_calls": []}),
    )
    update = make_update(text="catat servis")
    await ai_handlers.ai_message_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "Plat" in reply
    assert len(runtime.pending_store._items) == 0  # no fake pending action
    assert "reply_markup" not in update.message.reply_text.await_args.kwargs


@pytest.mark.asyncio
async def test_ai_message_handler_provider_error_no_mutation(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)

    class FailingDeepSeek:
        configured = True

        async def chat(self, messages, tools=None):
            raise AIProviderError("DeepSeek API gagal: timeout")

    runtime.deepseek = FailingDeepSeek()
    runtime.orchestrator = AIOrchestrator(runtime.deepseek, runtime.pending_store)

    update = make_update(text="catat servis")
    await ai_handlers.ai_message_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "❌" in reply
    session = db_factory()
    assert session.query(Vehicle).count() == 0
    session.close()


@pytest.mark.asyncio
async def test_ai_message_handler_search_read_no_pending(monkeypatch, db_factory):
    _install_runtime(
        monkeypatch,
        FakeDeepSeek({"content": "", "tool_calls": [
            _tool_call("search_vehicle_by_plate", '{"nopol": "B1234ABC"}')
        ]}),
    )
    session = db_factory()
    session.add(Vehicle(nama_client="Budi", nopol="B1234ABC"))
    session.commit()
    session.close()

    update = make_update(text="cari B1234ABC")
    await ai_handlers.ai_message_handler(update, MagicMock())

    assert "reply_markup" not in update.message.reply_text.await_args.kwargs  # read -> no confirm buttons


@pytest.mark.asyncio
async def test_ai_message_handler_report_no_pending(monkeypatch, db_factory):
    runtime = _install_runtime(
        monkeypatch,
        FakeDeepSeek({"content": "", "tool_calls": [
            _tool_call("report_activity_summary", "{}")
        ]}),
    )
    update = make_update(text="ringkasan aktivitas bengkel")
    await ai_handlers.ai_message_handler(update, MagicMock())

    assert len(runtime.pending_store._items) == 0  # report is read-only
    assert "reply_markup" not in update.message.reply_text.await_args.kwargs


# ---------------------------------------------------------------------------
# H7A Part A: cancel UX — valid/invalid/used/other-user/expired tokens
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_cancel_valid_token_reports_success(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    action = runtime.pending_store.add(123, [{"tool": "create_vehicle", "arguments": {"nopol": "B1234ABC"}}], "s")
    cb = make_update(callback_data=f"ai_cancel_{action.token}")
    await ai_handlers.ai_cancel_callback(cb, MagicMock())

    reply = cb.callback_query.edit_message_text.await_args[0][0]
    assert "Dibatalkan" in reply
    assert len(runtime.pending_store._items) == 0


@pytest.mark.asyncio
async def test_ai_cancel_rejects_invalid_token(monkeypatch, db_factory):
    _install_runtime(monkeypatch)
    cb = make_update(callback_data="ai_cancel_")
    await ai_handlers.ai_cancel_callback(cb, MagicMock())

    reply = cb.callback_query.edit_message_text.await_args[0][0]
    assert "tidak valid" in reply


@pytest.mark.asyncio
async def test_ai_cancel_rejects_other_user(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    action = runtime.pending_store.add(123, [{"tool": "create_vehicle", "arguments": {"nopol": "B1234ABC"}}], "s")
    cb = make_update(user_id=999, callback_data=f"ai_cancel_{action.token}")
    await ai_handlers.ai_cancel_callback(cb, MagicMock())

    reply = cb.callback_query.edit_message_text.await_args[0][0]
    assert "tidak valid" in reply
    assert len(runtime.pending_store._items) == 1  # other user's token NOT removed


@pytest.mark.asyncio
async def test_ai_cancel_rejects_used_token(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    action = runtime.pending_store.add(123, [{"tool": "create_vehicle", "arguments": {"nopol": "B1234ABC"}}], "s")
    await ai_handlers.ai_cancel_callback(make_update(callback_data=f"ai_cancel_{action.token}"), MagicMock())
    cb2 = make_update(callback_data=f"ai_cancel_{action.token}")
    await ai_handlers.ai_cancel_callback(cb2, MagicMock())

    reply = cb2.callback_query.edit_message_text.await_args[0][0]
    assert "tidak valid" in reply  # token already consumed


@pytest.mark.asyncio
async def test_ai_cancel_rejects_expired_token(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    action = runtime.pending_store.add(123, [{"tool": "create_vehicle", "arguments": {"nopol": "B1234ABC"}}], "s")
    runtime.pending_store._ttl = 0  # expire immediately
    cb = make_update(callback_data=f"ai_cancel_{action.token}")
    await ai_handlers.ai_cancel_callback(cb, MagicMock())

    reply = cb.callback_query.edit_message_text.await_args[0][0]
    assert "tidak valid" in reply


@pytest.mark.asyncio
async def test_ai_cancel_denies_unauthorized(monkeypatch, db_factory):
    _install_runtime(monkeypatch)
    monkeypatch.setattr("bot.auth.is_authorized", lambda uid: False)
    cb = make_update(callback_data="ai_cancel_sometoken")
    await ai_handlers.ai_cancel_callback(cb, MagicMock())

    cb.callback_query.edit_message_text.assert_not_awaited()  # denied before handler body


# ---------------------------------------------------------------------------
# H7A Part B: photo handler flow (mock Gemini + isolated DB)
# ---------------------------------------------------------------------------

def _photo_update(monkeypatch, extract_result=None):
    runtime = _install_runtime(monkeypatch)
    runtime.gemini = MagicMock()
    runtime.gemini.configured = True
    if extract_result is None:
        runtime.gemini.extract = AsyncMock(side_effect=AIProviderError("Gemini gagal"))
    else:
        runtime.gemini.extract = AsyncMock(return_value=extract_result)

    update = make_update()
    update.message.caption = None  # no caption by default (plate from extraction)
    photo = MagicMock()
    photo.file_size = 1024
    file = MagicMock()
    file.download_as_bytearray = AsyncMock(return_value=b"\xff\xd8\xffjpeg-data")
    photo.get_file = AsyncMock(return_value=file)
    update.message.photo = [photo]
    return runtime, update


@pytest.mark.asyncio
async def test_ai_photo_handler_valid_creates_pending(monkeypatch, db_factory):
    session = db_factory()
    session.add(Vehicle(nama_client="Budi", nopol="B1234ABC"))
    session.commit()
    session.close()

    runtime, update = _photo_update(
        monkeypatch,
        '{"plat": "B1234ABC", "jobs": [{"deskripsi": "Ganti oli", "harga": 50000}]}',
    )
    await ai_handlers.ai_photo_handler(update, MagicMock())

    assert len(runtime.pending_store._items) == 1
    reply = update.message.reply_text.await_args[0][0]
    assert "Periksa data servis" in reply
    token = next(iter(runtime.pending_store._items))
    assert runtime.pending_store._items[token].steps[0]["tool"] == "add_service_record"
    # no mutation before confirmation
    session = db_factory()
    assert session.query(ServiceRecord).count() == 0
    session.close()


@pytest.mark.asyncio
async def test_ai_photo_handler_missing_plate_asks_plate(monkeypatch, db_factory):
    runtime, update = _photo_update(
        monkeypatch,
        '{"jobs": [{"deskripsi": "Ganti oli"}]}',  # no plat
    )
    await ai_handlers.ai_photo_handler(update, MagicMock())

    assert len(runtime.pending_store._items) == 0
    reply = update.message.reply_text.await_args[0][0]
    assert "Silakan kirim nomor plat" in reply
    assert runtime.photo_drafts.pop(update.effective_user.id) is not None


@pytest.mark.asyncio
async def test_ai_photo_handler_new_vehicle_creates_pending(monkeypatch, db_factory):
    runtime, update = _photo_update(
        monkeypatch,
        '{"plat": "B9999XXX", "jobs": [{"deskripsi": "Ganti oli", "harga": 50000}]}',  # unknown vehicle
    )
    await ai_handlers.ai_photo_handler(update, MagicMock())

    assert len(runtime.pending_store._items) == 1
    token = next(iter(runtime.pending_store._items))
    step = runtime.pending_store._items[token].steps[0]
    assert step["tool"] == "record_service_visit"
    assert step["arguments"]["nama_client"] is None  # no name invented
    reply = update.message.reply_text.await_args[0][0]
    assert "kendaraan baru" in reply
    # no mutation before confirmation
    session = db_factory()
    assert session.query(Vehicle).count() == 0
    assert session.query(ServiceRecord).count() == 0
    session.close()


@pytest.mark.asyncio
async def test_ai_photo_handler_extraction_empty_refuses(monkeypatch, db_factory):
    runtime, update = _photo_update(monkeypatch, "not-json")
    await ai_handlers.ai_photo_handler(update, MagicMock())

    assert len(runtime.pending_store._items) == 0
    reply = update.message.reply_text.await_args[0][0]
    assert "Tidak dapat membaca" in reply


@pytest.mark.asyncio
async def test_ai_photo_handler_extraction_error_refuses(monkeypatch, db_factory):
    runtime, update = _photo_update(monkeypatch)  # extract raises AIProviderError
    await ai_handlers.ai_photo_handler(update, MagicMock())

    assert len(runtime.pending_store._items) == 0
    reply = update.message.reply_text.await_args[0][0]
    assert "❌" in reply


@pytest.mark.asyncio
async def test_ai_photo_handler_confirm_saves(monkeypatch, db_factory):
    session = db_factory()
    session.add(Vehicle(nama_client="Budi", nopol="B1234ABC"))
    session.commit()
    session.close()

    runtime, update = _photo_update(
        monkeypatch,
        '{"plat": "B1234ABC", "jobs": [{"deskripsi": "Ganti oli", "harga": 50000}]}',
    )
    await ai_handlers.ai_photo_handler(update, MagicMock())

    token = next(iter(runtime.pending_store._items))
    cb = make_update(callback_data=f"ai_confirm_{token}")
    await ai_handlers.ai_confirm_callback(cb, MagicMock())

    session = db_factory()
    assert session.query(ServiceRecord).count() == 1
    record = session.query(ServiceRecord).one()
    assert record.biaya_jasa == Decimal("50000.00")
    assert [j.deskripsi for j in record.jobs] == ["Ganti oli"]
    session.close()


@pytest.mark.asyncio
async def test_ai_photo_handler_cancel_no_mutation(monkeypatch, db_factory):
    session = db_factory()
    session.add(Vehicle(nama_client="Budi", nopol="B1234ABC"))
    session.commit()
    session.close()

    runtime, update = _photo_update(
        monkeypatch,
        '{"plat": "B1234ABC", "jobs": [{"deskripsi": "Ganti oli", "harga": 50000}]}',
    )
    await ai_handlers.ai_photo_handler(update, MagicMock())

    token = next(iter(runtime.pending_store._items))
    cb = make_update(callback_data=f"ai_cancel_{token}")
    await ai_handlers.ai_cancel_callback(cb, MagicMock())

    session = db_factory()
    assert session.query(ServiceRecord).count() == 0
    session.close()
    assert len(runtime.pending_store._items) == 0


@pytest.mark.asyncio
async def test_ai_photo_handler_denies_unauthorized(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    runtime.gemini = MagicMock()
    runtime.gemini.configured = True
    monkeypatch.setattr("bot.auth.is_authorized", lambda uid: False)

    update = make_update()
    update.message.photo = [MagicMock()]
    await ai_handlers.ai_photo_handler(update, MagicMock())

    reply = update.message.reply_text.await_args[0][0]
    assert "tidak memiliki akses" in reply
    runtime.gemini.extract.assert_not_called()


@pytest.mark.asyncio
async def test_ai_photo_handler_invalid_harga_rolls_back(monkeypatch, db_factory):
    session = db_factory()
    session.add(Vehicle(nama_client="Budi", nopol="B1234ABC"))
    session.commit()
    session.close()

    runtime, update = _photo_update(
        monkeypatch,
        '{"plat": "B1234ABC", "jobs": [{"deskripsi": "Ganti oli", "harga": "abc"}]}',
    )
    await ai_handlers.ai_photo_handler(update, MagicMock())

    token = next(iter(runtime.pending_store._items))
    cb = make_update(callback_data=f"ai_confirm_{token}")
    await ai_handlers.ai_confirm_callback(cb, MagicMock())

    reply = cb.callback_query.edit_message_text.await_args[0][0]
    assert "❌" in reply  # validation error surfaced
    session = db_factory()
    assert session.query(ServiceRecord).count() == 0  # rolled back, no mutation
    session.close()


# ---------------------------------------------------------------------------
# H7C: new-vehicle photo flow + confirmation message accuracy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_photo_new_vehicle_confirm_saves(monkeypatch, db_factory):
    runtime, update = _photo_update(
        monkeypatch,
        '{"plat": "B9999XXX", "jobs": [{"deskripsi": "Ganti oli", "harga": 50000}]}',
    )
    await ai_handlers.ai_photo_handler(update, MagicMock())

    token = next(iter(runtime.pending_store._items))
    cb = make_update(callback_data=f"ai_confirm_{token}")
    await ai_handlers.ai_confirm_callback(cb, MagicMock())

    session = db_factory()
    assert session.query(Vehicle).count() == 1
    assert session.query(ServiceRecord).count() == 1
    vehicle = session.query(Vehicle).one()
    assert vehicle.nopol == "B9999XXX"
    assert vehicle.nama_client is None  # no name invented
    assert vehicle.nomor_wa is None
    session.close()


@pytest.mark.asyncio
async def test_ai_photo_plate_followup_continues(monkeypatch, db_factory):
    runtime, update = _photo_update(
        monkeypatch,
        '{"jobs": [{"deskripsi": "Ganti oli", "harga": 50000}]}',  # no plat
    )
    await ai_handlers.ai_photo_handler(update, MagicMock())
    assert len(runtime.pending_store._items) == 0  # asked for plate, no pending yet

    text_update = make_update(text="B 1431 CVD")
    await ai_handlers.ai_message_handler(text_update, MagicMock())

    assert len(runtime.pending_store._items) == 1
    token = next(iter(runtime.pending_store._items))
    step = runtime.pending_store._items[token].steps[0]
    assert step["tool"] == "record_service_visit"
    assert step["arguments"]["nopol"] == "B1431CVD"  # normalized
    assert runtime.photo_drafts.pop(update.effective_user.id) is None  # draft consumed once


@pytest.mark.asyncio
async def test_ai_photo_caption_plate_used(monkeypatch, db_factory):
    runtime, update = _photo_update(
        monkeypatch,
        '{"plat": "B9999XXX", "jobs": [{"deskripsi": "Ganti oli", "harga": 50000}]}',
    )
    update.message.caption = "B 1431 CVD"  # caption overrides extracted plat
    await ai_handlers.ai_photo_handler(update, MagicMock())

    token = next(iter(runtime.pending_store._items))
    step = runtime.pending_store._items[token].steps[0]
    assert step["arguments"]["nopol"] == "B1431CVD"


@pytest.mark.asyncio
async def test_ai_photo_empty_plate_reply_no_mutation(monkeypatch, db_factory):
    runtime, update = _photo_update(monkeypatch, '{"jobs": [{"deskripsi": "Ganti oli"}]}')
    await ai_handlers.ai_photo_handler(update, MagicMock())  # asks plate

    text_update = make_update(text="   ")  # whitespace -> empty
    await ai_handlers.ai_message_handler(text_update, MagicMock())

    session = db_factory()
    assert session.query(Vehicle).count() == 0
    assert session.query(ServiceRecord).count() == 0
    session.close()


@pytest.mark.asyncio
async def test_ai_photo_new_vehicle_confirm_race_no_duplicate(monkeypatch, db_factory):
    runtime, update = _photo_update(
        monkeypatch,
        '{"plat": "B9999XXX", "jobs": [{"deskripsi": "Ganti oli", "harga": 50000}]}',
    )
    await ai_handlers.ai_photo_handler(update, MagicMock())  # new-vehicle pending

    # Another user registers the same plate before confirmation.
    session = db_factory()
    session.add(Vehicle(nama_client="OrangLain", nopol="B9999XXX"))
    session.commit()
    session.close()

    token = next(iter(runtime.pending_store._items))
    cb = make_update(callback_data=f"ai_confirm_{token}")
    await ai_handlers.ai_confirm_callback(cb, MagicMock())

    session = db_factory()
    assert session.query(Vehicle).count() == 1  # no duplicate vehicle
    assert session.query(ServiceRecord).count() == 1  # service appended to existing
    session.close()


@pytest.mark.asyncio
async def test_ai_confirm_failure_shows_error_not_success(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    action = runtime.pending_store.add(
        123,
        [{"tool": "record_service_visit", "arguments": {
            "nopol": "B1234ABC", "nama_client": "Budi",
            "parts": [{"nama_part": "Radiator", "jumlah": 0}],
        }}],
        "s",
    )
    cb = make_update(callback_data=f"ai_confirm_{action.token}")
    await ai_handlers.ai_confirm_callback(cb, MagicMock())

    reply = cb.callback_query.edit_message_text.await_args[0][0]
    assert "Berhasil" not in reply
    assert "❌" in reply
    session = db_factory()
    assert session.query(Vehicle).count() == 0  # rolled back
    assert session.query(ServiceRecord).count() == 0
    session.close()


@pytest.mark.asyncio
async def test_ai_confirm_success_shows_success(monkeypatch, db_factory):
    runtime = _install_runtime(monkeypatch)
    action = runtime.pending_store.add(
        123,
        [{"tool": "record_service_visit", "arguments": {
            "nopol": "B1234ABC", "nama_client": "Budi",
            "jobs": [{"deskripsi": "Ganti oli", "harga": 50000}],
        }}],
        "s",
    )
    cb = make_update(callback_data=f"ai_confirm_{action.token}")
    await ai_handlers.ai_confirm_callback(cb, MagicMock())

    reply = cb.callback_query.edit_message_text.await_args[0][0]
    assert "Berhasil" in reply
    session = db_factory()
    assert session.query(Vehicle).count() == 1
    assert session.query(ServiceRecord).count() == 1
    session.close()
