"""Tests for plate+name identification and owner-takeover fallback."""

from services.service_record_service import ServiceRecordService
from services.vehicle_service import VehicleService
from whatsapp.agent import WhatsAppAgent, run_restricted_tool
from whatsapp.services import ContactService


def _vehicle(session):
    return VehicleService(session).create_vehicle(
        nama_client="Budi", nopol="B1002BBB", nomor_wa="0851", jenis_mobil="Toyota Avanza", tahun_mobil=2020
    )


def test_lookup_by_plate_matches_name_and_links(session, wa_session):
    _vehicle(session)
    contact = ContactService(wa_session).get_or_create("105326221250596")
    wa_session.commit()

    out = run_restricted_tool("lookup_by_plate", {"nopol": "B1002BBB", "nama": "Budi"}, contact, wa_session, session)
    assert "Kendaraan terverifikasi" in out

    c2 = ContactService(wa_session).get(contact.id)
    assert c2.linked_vehicle_id is not None
    assert c2.linked_vehicle_nopol == "B1002BBB"
    assert c2.nama == "Budi"


def test_lookup_by_plate_name_mismatch_rejected(session, wa_session):
    _vehicle(session)
    contact = ContactService(wa_session).get_or_create("105326221250596")
    wa_session.commit()

    out = run_restricted_tool("lookup_by_plate", {"nopol": "B1002BBB", "nama": "Andi"}, contact, wa_session, session)
    assert "Nama tidak cocok" in out
    assert ContactService(wa_session).get(contact.id).linked_vehicle_id is None


def test_lookup_by_plate_not_found(session, wa_session):
    contact = ContactService(wa_session).get_or_create("105326221250596")
    wa_session.commit()

    out = run_restricted_tool("lookup_by_plate", {"nopol": "Z9999ZZZ", "nama": "Budi"}, contact, wa_session, session)
    assert "Plat tidak ditemukan" in out
    assert ContactService(wa_session).get(contact.id).linked_vehicle_id is None


def test_context_uses_linked_vehicle(session, wa_session):
    v = _vehicle(session)
    contact = ContactService(wa_session).get_or_create("105326221250596")
    ContactService(wa_session).update_memory(contact.id, linked_vehicle_id=v.id, linked_vehicle_nopol="B1002BBB")
    wa_session.commit()

    ctx = WhatsAppAgent()._context(contact, session)
    assert "B1002BBB" in ctx


def test_lookup_customer_uses_linked_vehicle(session, wa_session):
    v = _vehicle(session)
    contact = ContactService(wa_session).get_or_create("105326221250596")
    ContactService(wa_session).update_memory(contact.id, linked_vehicle_id=v.id)
    wa_session.commit()

    out = run_restricted_tool("lookup_customer", {}, contact, wa_session, session)
    assert "B1002BBB" in out


def test_service_history_authorized_via_linked_vehicle(session, wa_session):
    v = _vehicle(session)
    ServiceRecordService(session).add_service_record(v.id, jobs=[{"deskripsi": "Ganti Oli", "jumlah": 1, "harga": 150000}])
    contact = ContactService(wa_session).get_or_create("105326221250596")
    ContactService(wa_session).update_memory(contact.id, linked_vehicle_id=v.id)
    wa_session.commit()

    out = run_restricted_tool("get_service_history", {"vehicle_id": v.id}, contact, wa_session, session)
    assert "Ganti Oli" in out


def test_service_history_cross_user_still_denied(session, wa_session):
    v = _vehicle(session)
    ServiceRecordService(session).add_service_record(v.id, jobs=[{"deskripsi": "Ganti Oli", "jumlah": 1, "harga": 150000}])
    # different contact WITHOUT linked_vehicle_id, different number
    contact = ContactService(wa_session).get_or_create("0812-999")
    wa_session.commit()

    out = run_restricted_tool("get_service_history", {"vehicle_id": v.id}, contact, wa_session, session)
    assert "Akses ditolak" in out
