"""Regression tests for WA-HARDENING-MASTER-02 changes (send status, warranty, safety)."""

import asyncio

from sqlalchemy.exc import OperationalError

from whatsapp.agent import DB_UNAVAILABLE_REPLY, WhatsAppAgent, run_restricted_tool
from whatsapp.services import (
    ContactService,
    MatchingService,
    PriceService,
    send_status_of,
)


def test_send_status_of_helper():
    assert send_status_of({"sent": True}) == "sent"
    assert send_status_of({"sent": False, "error": "x"}) == "failed"
    assert send_status_of({"error": "conn refused", "status": "bridge_unavailable"}) == "unknown"


def test_mark_send_status(wa_session):
    from whatsapp.models import WaMessage

    c = ContactService(wa_session).get_or_create("0812-1")
    _, msg = ContactService(wa_session).record_message(c.id, "ai", "halo")
    wa_session.commit()

    ContactService(wa_session).mark_send_status(msg.id, "sent")
    wa_session.commit()
    assert wa_session.get(WaMessage, msg.id).send_status == "sent"


def test_part_price_not_found_does_not_leak_catalog(session):
    assert PriceService(session).part_price("barang tidak ada sama sekali") is None
    assert PriceService(session).jasa_price("layanan tidak ada") is None


def test_service_history_includes_warranty(session):
    from services.service_record_service import ServiceRecordService
    from services.vehicle_service import VehicleService

    v = VehicleService(session).create_vehicle(nama_client="Budi", nopol="B1", nomor_wa="0812-1")
    ServiceRecordService(session).add_service_record(
        v.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}], garansi_sampai="2026-12-31"
    )
    hist = MatchingService(session).service_history(v.id, "0812-1")
    assert len(hist) == 1
    assert hist[0]["garansi_sampai"] == "31/12/2026"
    assert hist[0]["bergaransi"] is True
    assert hist[0]["status_klaim"] == "Belum claim"


def test_service_history_warranty_absent_is_none(session):
    from services.service_record_service import ServiceRecordService
    from services.vehicle_service import VehicleService

    v = VehicleService(session).create_vehicle(nama_client="Budi", nopol="B1", nomor_wa="0812-1")
    ServiceRecordService(session).add_service_record(v.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}])
    hist = MatchingService(session).service_history(v.id, "0812-1")
    assert hist[0]["garansi_sampai"] is None
    assert hist[0]["bergaransi"] is None


def test_agent_short_circuits_when_tool_reports_db_unavailable(wa_session, session, monkeypatch):
    ContactService(wa_session).get_or_create("0812-1")
    wa_session.commit()

    calls = {"n": 0}

    class FakeProvider:
        configured = True

        async def chat(self, messages, tools=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "content": None,
                    "tool_calls": [{"id": "t1", "type": "function", "function": {"name": "check_stock", "arguments": '{"nama_part": "Oli"}'}}],
                }
            return {"content": "should not reach here", "tool_calls": []}

    def boom(*a, **k):
        raise OperationalError("SELECT ...", None, None)

    monkeypatch.setattr(PriceService, "check_stock", boom)

    agent = WhatsAppAgent()
    agent._provider = FakeProvider()
    reply = asyncio.run(agent.reply("0812-1", "cek stok oli", wa_session, session))

    assert reply == DB_UNAVAILABLE_REPLY
    assert calls["n"] == 1  # short-circuited; provider not called a second time


def test_get_service_history_tool_includes_warranty(session, wa_session):
    from services.service_record_service import ServiceRecordService
    from services.vehicle_service import VehicleService

    v = VehicleService(session).create_vehicle(nama_client="Budi", nopol="B1", nomor_wa="0812-1")
    ServiceRecordService(session).add_service_record(
        v.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}], garansi_sampai="2026-12-31"
    )
    contact = ContactService(wa_session).get_or_create("0812-1")
    out = run_restricted_tool("get_service_history", {"vehicle_id": v.id}, contact, wa_session, session)
    assert "garansi_sampai=31/12/2026" in out
    assert "status_klaim=Belum claim" in out
