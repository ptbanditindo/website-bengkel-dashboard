"""Tests for AI tool definitions, dispatch, and pending store."""

from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

import ai.tools as tools
from ai.tools import (
    MUTATION_TOOLS,
    TOOL_SCHEMAS,
    PendingConfirmation,
    PendingStore,
    PhotoDraftStore,
    ReadResult,
    execute_mutation,
    plan_tool,
)
from database.models import ServiceRecord, Vehicle
from services.exceptions import ConflictError


@pytest.fixture()
def db_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _add_vehicle(session, nama="Budi", nopol="B1234ABC"):
    v = Vehicle(nama_client=nama, nopol=nopol)
    session.add(v)
    session.commit()
    return v


def test_tool_schemas_defined():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert "search_vehicle_by_plate" in names
    assert "create_vehicle" in names
    assert "add_service_record" in names
    assert "record_service_visit" in names
    assert "confirm_warranty_claim" in names
    assert "report_activity_summary" in names
    assert "search_service_records_by_job" in names
    assert len(TOOL_SCHEMAS) == 20


def test_mutation_tools_set():
    assert "create_vehicle" in MUTATION_TOOLS
    assert "add_service_record" in MUTATION_TOOLS
    assert "record_service_visit" in MUTATION_TOOLS
    assert "search_vehicle_by_plate" not in MUTATION_TOOLS


def test_search_vehicle_by_plate_read(db_factory):
    session = db_factory()
    _add_vehicle(session)
    result = plan_tool("search_vehicle_by_plate", {"nopol": "b 1234 abc"}, session)
    assert isinstance(result, ReadResult)
    assert "Budi" in result.data
    session.close()


def test_search_vehicle_not_found(db_factory):
    session = db_factory()
    result = plan_tool("search_vehicle_by_plate", {"nopol": "ZZZZ"}, session)
    assert "tidak ditemukan" in result.data
    session.close()


def test_create_vehicle_plans_confirmation(db_factory):
    session = db_factory()
    result = plan_tool("create_vehicle", {"nama_client": "Budi", "nopol": "B 1234 ABC"}, session)
    assert isinstance(result, PendingConfirmation)
    assert result.tool_name == "create_vehicle"
    assert "Budi" in result.summary
    assert session.query(Vehicle).count() == 0  # not persisted
    session.close()


def test_create_vehicle_duplicate_raises(db_factory):
    session = db_factory()
    _add_vehicle(session)
    with pytest.raises(ConflictError):
        plan_tool("create_vehicle", {"nama_client": "Andi", "nopol": "B1234ABC"}, session)
    session.close()


def test_execute_create_vehicle(db_factory):
    session = db_factory()
    text = execute_mutation(
        "create_vehicle", {"nama_client": "Budi", "nopol": "B1234ABC", "tahun_mobil": 2020}, session
    )
    assert "berhasil didaftarkan" in text
    assert session.query(Vehicle).count() == 1
    session.close()


def test_add_service_record_plans_and_executes(db_factory):
    session = db_factory()
    _add_vehicle(session)
    result = plan_tool(
        "add_service_record",
        {
            "nopol": "B1234ABC",
            "jobs": [{"deskripsi": "Pasang radiator", "jumlah": 1, "harga": 150000}],
            "parts": [{"nama_part": "Radiator", "jumlah": 1, "harga_satuan": 850000}],
        },
        session,
    )
    assert isinstance(result, PendingConfirmation)
    assert "Pasang radiator" in result.summary
    assert session.query(ServiceRecord).count() == 0  # not executed yet

    text = execute_mutation("add_service_record", result.arguments, session)
    assert "Pasang radiator" in text
    assert session.query(ServiceRecord).count() == 1
    session.close()


def test_record_service_visit_plans_and_executes(db_factory):
    session = db_factory()
    result = plan_tool(
        "record_service_visit",
        {
            "nopol": "B 3413 FED",
            "nama_client": "Dhani",
            "total": "600rb",
            "jobs": [{"deskripsi": "ganti radiator"}],
        },
        session,
    )
    assert isinstance(result, PendingConfirmation)
    assert result.tool_name == "record_service_visit"
    assert session.query(Vehicle).count() == 0  # not persisted

    text = execute_mutation("record_service_visit", result.arguments, session)
    assert "ganti radiator" in text
    assert session.query(Vehicle).count() == 1
    assert session.query(ServiceRecord).count() == 1
    session.close()


def test_pending_store_one_time():
    store = PendingStore()
    action = store.add(123, [{"tool": "create_vehicle", "arguments": {"nopol": "B1234ABC"}}], "summary")
    assert store.get(action.token, 123) is not None
    assert store.pop(action.token, 123) is not None
    assert store.pop(action.token, 123) is None  # one-time use


def test_pending_store_user_bound():
    store = PendingStore()
    action = store.add(123, [{"tool": "create_vehicle", "arguments": {"nopol": "B1234ABC"}}], "summary")
    assert store.get(action.token, 999) is None  # different user cannot read
    assert store.pop(action.token, 999) is None


def test_pending_store_expires():
    import time

    store = PendingStore(ttl_seconds=0)
    action = store.add(123, [{"tool": "create_vehicle", "arguments": {"nopol": "B1234ABC"}}], "summary")
    time.sleep(0.01)
    assert store.pop(action.token, 123) is None  # expired


def test_photo_draft_store_user_bound():
    store = PhotoDraftStore()
    store.add(123, {"jobs": []})
    assert store.pop(999) is None  # other user cannot pop
    assert store.pop(123) is not None


def test_photo_draft_store_expires():
    import time

    store = PhotoDraftStore(ttl_seconds=0)
    store.add(123, {"jobs": []})
    time.sleep(0.01)
    assert store.pop(123) is None  # expired


def test_add_service_record_plan_defers_vehicle_and_keeps_total(db_factory):
    session = db_factory()
    result = plan_tool(
        "add_service_record",
        {"nopol": "B 3413 FED", "total": "600000", "jobs": [{"deskripsi": "ganti radiator"}]},
        session,
    )
    assert isinstance(result, PendingConfirmation)
    assert result.arguments["nopol"] == "B3413FED"  # normalized
    assert result.arguments["total"] == "600000"
    assert "ganti radiator" in result.summary
    assert session.query(ServiceRecord).count() == 0  # not persisted
    session.close()


def test_execute_add_service_record_with_total(db_factory):
    session = db_factory()
    _add_vehicle(session)  # B1234ABC
    text = execute_mutation(
        "add_service_record",
        {"nopol": "B1234ABC", "total": "600000", "jobs": [{"deskripsi": "ganti radiator"}]},
        session,
    )
    assert "ganti radiator" in text
    record = session.query(ServiceRecord).one()
    assert record.total_servis == Decimal("600000.00")
    assert record.biaya_jasa is None  # breakdown unknown, not invented
    session.close()
