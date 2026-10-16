"""Tests for WhatsApp CS core: db, normalize, isolation, dedup, queue, gateway, agent security."""

import pytest
from sqlalchemy.orm import sessionmaker

from database.models import HargaJasa, StockItem, Vehicle
from services.exceptions import ValidationError
from services.harga_jasa_service import HargaJasaService
from services.service_record_service import ServiceRecordService
from services.stock_service import StockService
from services.vehicle_service import VehicleService
from whatsapp.agent import WA_SECURITY_RULES, build_system_prompt, run_restricted_tool
from whatsapp.gateway import MockGateway
from whatsapp.normalize import normalize_wa_number
from whatsapp.queue import PerNumberQueue
from whatsapp.services import (
    ArrivalService,
    ContactService,
    MatchingService,
    PriceService,
    QuestionService,
    SettingsService,
)


def test_normalize_phone():
    assert normalize_wa_number("0812-3456-7890") == "6281234567890"
    assert normalize_wa_number("+62 812 3456") == "628123456"
    assert normalize_wa_number("") == ""


def test_settings_default_safe(wa_session):
    s = SettingsService(wa_session).get()
    assert s.id == 1
    assert s.default_delay_seconds == 60
    assert s.redirect_enabled == 1


def test_persistence_after_reopen(wa_engine):
    factory = sessionmaker(bind=wa_engine, autoflush=False, expire_on_commit=False)
    s1 = factory()
    c = ContactService(s1).get_or_create("0812-1")
    ContactService(s1).update_memory(c.id, nama="Budi")
    s1.commit()
    s1.close()
    s2 = factory()
    assert ContactService(s2).get_or_create("0812-1").nama == "Budi"
    s2.close()


def test_memory_isolation_between_numbers(wa_session):
    c1 = ContactService(wa_session).get_or_create("0812-1")
    c2 = ContactService(wa_session).get_or_create("0812-2")
    ContactService(wa_session).update_memory(c1.id, nama="A", plat="B1")
    ContactService(wa_session).update_memory(c2.id, nama="B", plat="B2")
    wa_session.commit()
    a = ContactService(wa_session).get_or_create("0812-1")
    b = ContactService(wa_session).get_or_create("0812-2")
    assert a.nama == "A" and a.plat == "B1"
    assert b.nama == "B" and b.plat == "B2"
    assert a.id != b.id


def test_message_dedup_by_gateway_id(wa_session):
    c = ContactService(wa_session).get_or_create("0812-1")
    created1, m1 = ContactService(wa_session).record_message(c.id, "customer", "halo", "gw-1")
    created2, m2 = ContactService(wa_session).record_message(c.id, "customer", "halo", "gw-1")
    wa_session.commit()
    assert created1 is True and created2 is False
    assert m1.id == m2.id


def test_queue_per_number_independent():
    q = PerNumberQueue(default_delay_seconds=100)
    q.enqueue("A", "msg-a", 100)
    q.enqueue("B", "msg-b", 0)
    due = [n for n, _ in q.pop_due()]
    assert "B" in due
    assert "A" not in due


def test_gateway_mock_honest():
    g = MockGateway()
    assert g.status().connected is False
    assert g.status().provider == "mock"
    g.send_message("0812", "halo")
    assert len(g.sent) == 1


def test_matching_unique(session):
    VehicleService(session).create_vehicle(nama_client="Budi", nopol="B1234ABC", nomor_wa="0812-1")
    matches = MatchingService(session).match_by_wa_number("0812-1")
    assert len(matches) == 1
    assert matches[0].nopol == "B1234ABC"


def test_matching_none(session):
    assert MatchingService(session).match_by_wa_number("unknown") == []


def test_service_history_access_denied(session):
    v1 = VehicleService(session).create_vehicle(nama_client="Budi", nopol="B1", nomor_wa="0812-111")
    VehicleService(session).create_vehicle(nama_client="Andi", nopol="B2", nomor_wa="0812-222")
    ServiceRecordService(session).add_service_record(v1.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}])
    with pytest.raises(ValidationError):
        MatchingService(session).service_history(v1.id, "0812-222")


def test_service_history_allowed_for_owner(session):
    v1 = VehicleService(session).create_vehicle(nama_client="Budi", nopol="B1", nomor_wa="0812-111")
    ServiceRecordService(session).add_service_record(v1.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}])
    hist = MatchingService(session).service_history(v1.id, "0812-111")
    assert len(hist) == 1
    assert "Ganti oli" in hist[0]["pekerjaan"]
    assert "harga" not in hist[0]


def test_stock_check_no_quantity_and_no_change(session):
    StockService(session).create_item(nama="Oli mesin", kode="OLI", harga_modal=50000, harga_jual=80000, jumlah=5)
    assert PriceService(session).check_stock("Oli mesin") == "tersedia"
    assert PriceService(session).part_price("Oli mesin") == 80000.0
    item = session.query(StockItem).first()
    assert item.jumlah == 5


def test_agent_tool_check_stock(session, wa_session):
    StockService(session).create_item(nama="Ban", kode="BAN", harga_modal=100000, harga_jual=150000, jumlah=3)
    contact = ContactService(wa_session).get_or_create("0812-1")
    out = run_restricted_tool("check_stock", {"nama_part": "Ban"}, contact, wa_session, session)
    assert out == "tersedia"
    assert "3" not in out


def test_agent_tool_price_sell_only(session, wa_session):
    StockService(session).create_item(nama="Ban", kode="BAN", harga_modal=100000, harga_jual=150000, jumlah=3)
    contact = ContactService(wa_session).get_or_create("0812-1")
    out = run_restricted_tool("get_part_price", {"nama_part": "Ban"}, contact, wa_session, session)
    assert "150.000" in out
    assert "100.000" not in out


def test_arrival_plan_is_not_actual_arrival(wa_session):
    c = ContactService(wa_session).get_or_create("0812-1")
    p = ArrivalService(wa_session).create_plan(c.id, rencana_hari="besok")
    assert p.status == "RENCANA"
    c2 = ContactService(wa_session).get(c.id)
    assert c2.arrival_status is None
    ArrivalService(wa_session).set_status(p.id, "DATANG")
    assert ArrivalService(wa_session).list()[0].status == "DATANG"
    assert ContactService(wa_session).get(c.id).arrival_status is None


def test_question_escalation(wa_session):
    c = ContactService(wa_session).get_or_create("0812-1")
    q = QuestionService(wa_session).create(c.id, c.wa_number, "Pertanyaan sulit", alasan="AI tidak tahu")
    assert q.status == "MENUNGGU"
    QuestionService(wa_session).answer(q.id, "Jawaban owner")
    assert QuestionService(wa_session).list()[0].status == "DIJAWAB"


def test_agent_prompt_has_security_rules(wa_session):
    s = SettingsService(wa_session).get()
    s.agent_prompt = "Jadilah ramah"
    prompt = build_system_prompt(s)
    assert "Jadilah ramah" in prompt
    assert WA_SECURITY_RULES.strip() in prompt
