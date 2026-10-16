"""Tests for WhatsApp candidate ACC/Tolak and dedup prevention."""

import pytest

from database.models import Vehicle
from services.exceptions import ConflictError, ValidationError
from services.vehicle_service import VehicleService
from whatsapp.services import CandidateService, ContactService


def _seed(wa_session, session, nopol="B1234ABC", wa_number="0812-1"):
    contact = ContactService(wa_session).get_or_create(wa_number)
    cand = CandidateService(wa_session, session).create(contact.id, nopol=nopol, nama="Budi", jenis_mobil="Avanza", tahun_mobil=2020)
    wa_session.commit()
    return contact, cand


def test_approve_creates_vehicle_no_service_record(wa_session, session):
    contact, cand = _seed(wa_session, session)
    approved = CandidateService(wa_session, session).approve(cand.id)
    assert approved.status == "DISETUJUI"
    assert approved.linked_vehicle_id is not None
    v = VehicleService(session).find_vehicle_by_plate("B1234ABC")
    assert v is not None
    assert v.nomor_wa == contact.wa_number
    assert len(v.service_records) == 0


def test_approve_reuses_existing_vehicle_no_duplicate(wa_session, session):
    VehicleService(session).create_vehicle(nama_client="Budi", nopol="B1234ABC", nomor_wa="0812-1")
    contact, cand = _seed(wa_session, session, nopol="B1234ABC")
    approved = CandidateService(wa_session, session).approve(cand.id)
    vehicles = [v for v in session.query(Vehicle).all() if v.nopol == "B1234ABC"]
    assert len(vehicles) == 1
    assert approved.linked_vehicle_id == vehicles[0].id


def test_approve_requires_plate(wa_session, session):
    contact, cand = _seed(wa_session, session, nopol="")
    with pytest.raises(ValidationError):
        CandidateService(wa_session, session).approve(cand.id)


def test_reject_keeps_contact_and_no_main_write(wa_session, session):
    contact, cand = _seed(wa_session, session)
    rejected = CandidateService(wa_session, session).reject(cand.id, alasan="bukan pelanggan")
    assert rejected.status == "DITOLAK"
    assert ContactService(wa_session).get(contact.id).registration_status == "DITOLAK"
    assert VehicleService(session).find_vehicle_by_plate("B1234ABC") is None


def test_approve_twice_conflict(wa_session, session):
    contact, cand = _seed(wa_session, session)
    CandidateService(wa_session, session).approve(cand.id)
    with pytest.raises(ConflictError):
        CandidateService(wa_session, session).approve(cand.id)
