"""Tests for the AI orchestrator (tool loop) with a mocked provider."""

import pytest
from sqlalchemy.orm import sessionmaker

from ai.context import ConversationHistory
from ai.errors import AIError, AIProviderError
from ai.orchestrator import AIOrchestrator
from ai.tools import PendingStore
from database.models import ServiceRecord, Vehicle
from services.exceptions import ValidationError


class FakeProvider:
    """A scripted DeepSeek provider for tests."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        return self._responses.pop(0)


class FailingProvider:
    async def chat(self, messages, tools=None):
        raise AIProviderError("DeepSeek API gagal: timeout")


def _resp(content="", tool_calls=None):
    return {"content": content, "tool_calls": tool_calls or []}


def _tool_call(name, arguments, call_id="call_1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


@pytest.fixture()
def db_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.mark.asyncio
async def test_handle_message_read_tool_then_answer(db_factory):
    session = db_factory()
    session.add(Vehicle(nama_client="Budi", nopol="B1234ABC"))
    session.commit()

    provider = FakeProvider([
        _resp(tool_calls=[_tool_call("search_vehicle_by_plate", '{"nopol": "B1234ABC"}')]),
        _resp(content="Mobil Budi plat B1234ABC sudah terdaftar."),
    ])
    orchestrator = AIOrchestrator(provider)
    result = await orchestrator.handle_message("cari mobil B1234ABC", session, ConversationHistory(), user_id=123)

    assert "Budi" in result.reply
    assert result.pending_action is None
    assert len(provider.calls) == 2
    session.close()


@pytest.mark.asyncio
async def test_handle_message_asks_clarification(db_factory):
    session = db_factory()
    provider = FakeProvider([_resp(content="Nomor polisi kendaraan berapa ya?")])
    orchestrator = AIOrchestrator(provider)
    result = await orchestrator.handle_message("catat servis", session, ConversationHistory(), user_id=123)

    assert "polisi" in result.reply
    assert result.pending_action is None
    session.close()


@pytest.mark.asyncio
async def test_handle_message_mutation_returns_pending(db_factory):
    session = db_factory()
    provider = FakeProvider([
        _resp(tool_calls=[_tool_call("create_vehicle", '{"nama_client": "Budi", "nopol": "B 1234 ABC"}')]),
        _resp(content="Siap disimpan."),
    ])
    orchestrator = AIOrchestrator(provider)
    result = await orchestrator.handle_message(
        "daftarkan mobil Budi plat B 1234 ABC", session, ConversationHistory(), user_id=123
    )

    assert result.pending_action is not None
    assert len(result.pending_action.steps) == 1
    assert result.pending_action.steps[0]["tool"] == "create_vehicle"
    assert result.pending_action.user_id == 123
    assert session.query(Vehicle).count() == 0  # not persisted
    session.close()


@pytest.mark.asyncio
async def test_execute_pending_runs_mutation(db_factory):
    session = db_factory()
    store = PendingStore()
    orchestrator = AIOrchestrator(FakeProvider([]), store)
    action = store.add(
        123, [{"tool": "create_vehicle", "arguments": {"nama_client": "Budi", "nopol": "B1234ABC"}}], "summary"
    )

    text = orchestrator.execute_pending(action.token, session, user_id=123)
    assert "berhasil didaftarkan" in text
    assert session.query(Vehicle).count() == 1

    # token is one-time
    with pytest.raises(Exception):
        orchestrator.execute_pending(action.token, session, user_id=123)
    session.close()


@pytest.mark.asyncio
async def test_execute_pending_rejects_wrong_user(db_factory):
    session = db_factory()
    store = PendingStore()
    orchestrator = AIOrchestrator(FakeProvider([]), store)
    action = store.add(
        123, [{"tool": "create_vehicle", "arguments": {"nama_client": "Budi", "nopol": "B1234ABC"}}], "summary"
    )

    with pytest.raises(Exception):
        orchestrator.execute_pending(action.token, session, user_id=999)

    assert session.query(Vehicle).count() == 0
    session.close()


@pytest.mark.asyncio
async def test_execute_pending_rolls_back_when_second_step_fails(db_factory):
    session = db_factory()
    store = PendingStore()
    orchestrator = AIOrchestrator(FakeProvider([]), store)
    action = store.add(
        123,
        [
            {"tool": "create_vehicle", "arguments": {"nama_client": "Budi", "nopol": "B1234ABC"}},
            # invalid quantity -> the add_service_record step must fail
            {"tool": "add_service_record", "arguments": {"nopol": "B1234ABC", "parts": [{"nama_part": "Radiator", "jumlah": 0}]}},
        ],
        "summary",
    )

    with pytest.raises(ValidationError):
        orchestrator.execute_pending(action.token, session, user_id=123)
    # The whole action rolled back: no orphan vehicle, no record.
    assert session.query(Vehicle).count() == 0
    assert session.query(ServiceRecord).count() == 0
    session.close()


@pytest.mark.asyncio
async def test_handle_message_record_service_visit_single_tool(db_factory):
    session = db_factory()
    provider = FakeProvider([
        _resp(tool_calls=[
            _tool_call(
                "record_service_visit",
                '{"nopol": "B 3413 FED", "nama_client": "Dhani", "total": "600rb", '
                '"jobs": [{"deskripsi": "ganti radiator"}]}',
            )
        ]),
        _resp(content="Siap disimpan."),
    ])
    orchestrator = AIOrchestrator(provider)
    result = await orchestrator.handle_message(
        "catat servis Dhani B 3413 FED ganti radiator total 600rb",
        session, ConversationHistory(), user_id=123,
    )

    assert result.pending_action is not None
    assert len(result.pending_action.steps) == 1
    assert result.pending_action.steps[0]["tool"] == "record_service_visit"
    assert session.query(Vehicle).count() == 0
    assert session.query(ServiceRecord).count() == 0

    text = orchestrator.execute_pending(result.pending_action.token, session, user_id=123)
    assert "ganti radiator" in text
    assert session.query(Vehicle).count() == 1
    assert session.query(ServiceRecord).count() == 1
    session.close()


@pytest.mark.asyncio
async def test_record_service_visit_skips_final_answer_call(db_factory):
    """H6A: record_service_visit must not trigger a wasted final-answer request."""
    session = db_factory()
    provider = FakeProvider([
        _resp(tool_calls=[
            _tool_call(
                "record_service_visit",
                '{"nopol": "B 3413 FED", "nama_client": "Dhani", "total": "600rb", '
                '"jobs": [{"deskripsi": "ganti radiator"}]}',
            )
        ]),
    ])
    orchestrator = AIOrchestrator(provider)
    result = await orchestrator.handle_message(
        "catat servis Dhani B 3413 FED ganti radiator total 600rb",
        session, ConversationHistory(), user_id=123,
    )

    assert result.pending_action is not None
    assert len(result.pending_action.steps) == 1
    assert result.pending_action.steps[0]["tool"] == "record_service_visit"
    assert len(provider.calls) == 1  # no wasted final-answer request
    assert session.query(Vehicle).count() == 0
    assert session.query(ServiceRecord).count() == 0
    session.close()


@pytest.mark.asyncio
async def test_record_service_visit_with_prior_read_uses_two_calls(db_factory):
    session = db_factory()
    provider = FakeProvider([
        _resp(tool_calls=[_tool_call("search_vehicle_by_plate", '{"nopol": "B 3413 FED"}')]),
        _resp(tool_calls=[
            _tool_call(
                "record_service_visit",
                '{"nopol": "B 3413 FED", "nama_client": "Dhani", "total": "600rb", '
                '"jobs": [{"deskripsi": "ganti radiator"}]}',
            )
        ]),
    ])
    orchestrator = AIOrchestrator(provider)
    result = await orchestrator.handle_message(
        "catat servis Dhani B 3413 FED ganti radiator total 600rb",
        session, ConversationHistory(), user_id=123,
    )

    assert result.pending_action is not None
    assert len(result.pending_action.steps) == 1
    assert result.pending_action.steps[0]["tool"] == "record_service_visit"
    assert len(provider.calls) == 2  # read + record, no final-answer
    assert session.query(Vehicle).count() == 0
    session.close()


@pytest.mark.asyncio
async def test_legacy_create_vehicle_still_uses_final_answer(db_factory):
    """H6A: the legacy single-mutation flow is NOT short-circuited."""
    session = db_factory()
    provider = FakeProvider([
        _resp(tool_calls=[_tool_call("create_vehicle", '{"nama_client": "Budi", "nopol": "B 1234 ABC"}')]),
        _resp(content="Siap disimpan."),
    ])
    orchestrator = AIOrchestrator(provider)
    result = await orchestrator.handle_message(
        "daftarkan mobil Budi plat B 1234 ABC", session, ConversationHistory(), user_id=123,
    )

    assert result.pending_action is not None
    assert len(result.pending_action.steps) == 1
    assert result.pending_action.steps[0]["tool"] == "create_vehicle"
    assert len(provider.calls) == 2  # legacy still requests the final answer
    assert session.query(Vehicle).count() == 0
    session.close()


@pytest.mark.asyncio
async def test_provider_error_returns_error_reply(db_factory):
    session = db_factory()
    orchestrator = AIOrchestrator(FailingProvider())
    result = await orchestrator.handle_message("halo", session, ConversationHistory(), user_id=123)

    assert "❌" in result.reply
    assert result.pending_action is None
    session.close()


@pytest.mark.asyncio
async def test_handle_message_collects_combined_mutations(db_factory):
    session = db_factory()
    provider = FakeProvider([
        _resp(tool_calls=[
            _tool_call("create_vehicle", '{"nama_client": "Dhani", "nopol": "B 3413 FED"}', "c1"),
            _tool_call(
                "add_service_record",
                '{"nopol": "B 3413 FED", "total": "600000", "jobs": [{"deskripsi": "ganti radiator"}]}',
                "c2",
            ),
        ]),
        _resp(content="Siap disimpan."),
    ])
    orchestrator = AIOrchestrator(provider)
    result = await orchestrator.handle_message(
        "tambah avanza 2021 ganti radiator total 600rb", session, ConversationHistory(), user_id=123
    )

    assert result.pending_action is not None
    assert len(result.pending_action.steps) == 2
    assert result.pending_action.steps[0]["tool"] == "create_vehicle"
    assert result.pending_action.steps[1]["tool"] == "add_service_record"
    # nothing persisted before confirmation
    assert session.query(Vehicle).count() == 0
    assert session.query(ServiceRecord).count() == 0

    text = orchestrator.execute_pending(result.pending_action.token, session, user_id=123)
    assert "berhasil didaftarkan" in text
    assert "ganti radiator" in text
    assert session.query(Vehicle).count() == 1
    assert session.query(ServiceRecord).count() == 1
    session.close()


def test_execute_pending_rejects_second_execution(db_factory):
    session = db_factory()
    store = PendingStore()
    orchestrator = AIOrchestrator(FakeProvider([]), store)
    action = store.add(
        123,
        [{"tool": "create_vehicle", "arguments": {"nama_client": "Budi", "nopol": "B 1234 ABC"}}],
        "summary",
    )
    first = orchestrator.execute_pending(action.token, session, user_id=123)
    assert "berhasil didaftarkan" in first
    assert session.query(Vehicle).count() == 1

    with pytest.raises(AIError):
        orchestrator.execute_pending(action.token, session, user_id=123)
    assert session.query(Vehicle).count() == 1  # no duplicate on double confirm
    session.close()
