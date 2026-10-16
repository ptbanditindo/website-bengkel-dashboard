"""Tests for the ServiceRecordService (jobs, parts, totals, warranty, rollback)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from database.models import CLAIM_BELUM, CLAIM_SUDAH, ServiceRecord, Vehicle
from services.exceptions import ConflictError, NotFoundError, ValidationError


@pytest.fixture()
def vehicle(vehicle_service):
    return vehicle_service.create_vehicle(nama_client="Budi", nopol="B1234ABC")


def test_add_service_record_with_jobs_and_parts(vehicle, service_record_service):
    record = service_record_service.add_service_record(
        vehicle.id,
        jobs=[{"deskripsi": "Pasang radiator", "jumlah": 1, "harga": 150000}],
        parts=[
            {"nama_part": "Radiator", "jumlah": 1, "harga_satuan": 850000},
            {"nama_part": "Air radiator", "jumlah": 2, "harga_satuan": 50000},
        ],
    )
    assert record.id is not None
    assert len(record.jobs) == 1
    assert len(record.parts) == 2
    assert record.biaya_jasa == Decimal("150000.00")
    assert record.total_part == Decimal("950000.00")
    assert record.total_servis == Decimal("1100000.00")


def test_add_service_record_defaults(vehicle, service_record_service):
    record = service_record_service.add_service_record(vehicle.id)
    assert record.status_klaim == CLAIM_BELUM
    assert record.garansi_sampai is None
    assert record.biaya_jasa == Decimal("0")
    assert record.total_part == Decimal("0")
    assert record.total_servis == Decimal("0")


def test_add_service_record_unknown_price_keeps_total_none(vehicle, service_record_service):
    record = service_record_service.add_service_record(
        vehicle.id,
        parts=[{"nama_part": "Radiator", "jumlah": 1}],  # no unit price
    )
    assert record.parts[0].harga_satuan is None
    assert record.parts[0].subtotal is None
    assert record.total_part is None
    assert record.total_servis is None


def test_multiple_service_records_not_overwritten(vehicle, service_record_service):
    r1 = service_record_service.add_service_record(
        vehicle.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}]
    )
    r2 = service_record_service.add_service_record(
        vehicle.id, jobs=[{"deskripsi": "Pasang radiator", "jumlah": 1, "harga": 150000}]
    )

    history = service_record_service.get_vehicle_service_history("B1234ABC")
    assert len(history) == 2
    assert r1.id != r2.id


def test_warranty_saved_and_mark_claim(vehicle, service_record_service):
    record = service_record_service.add_service_record(
        vehicle.id,
        garansi_sampai=date(2027, 1, 14),
        jobs=[{"deskripsi": "Pasang radiator", "jumlah": 1, "harga": 150000}],
    )
    assert record.garansi_sampai == date(2027, 1, 14)
    assert record.status_klaim == CLAIM_BELUM

    updated = service_record_service.mark_claim(record.id)
    assert updated.status_klaim == CLAIM_SUDAH


def test_mark_claim_only_affects_target_record(vehicle, service_record_service):
    r1 = service_record_service.add_service_record(vehicle.id)
    r2 = service_record_service.add_service_record(vehicle.id)

    service_record_service.mark_claim(r1.id)

    assert service_record_service.get_service_record(r1.id).status_klaim == CLAIM_SUDAH
    assert service_record_service.get_service_record(r2.id).status_klaim == CLAIM_BELUM


def test_warranty_bergaransi_requires_date(vehicle, service_record_service):
    with pytest.raises(ValidationError):
        service_record_service.add_service_record(vehicle.id, bergaransi=True)
    record = service_record_service.add_service_record(
        vehicle.id, bergaransi=True, garansi_sampai="2 agustus 2027"
    )
    assert record.bergaransi is True
    assert record.garansi_sampai == date(2027, 8, 2)


def test_warranty_tidak_bergaransi_clears_date(vehicle, service_record_service):
    record = service_record_service.add_service_record(
        vehicle.id, bergaransi=False, garansi_sampai=date(2027, 8, 2)
    )
    assert record.bergaransi is False
    assert record.garansi_sampai is None


def test_claim_with_tanggal_klaim(vehicle, service_record_service):
    record = service_record_service.add_service_record(
        vehicle.id, bergaransi=True, garansi_sampai=date(2027, 8, 2)
    )
    updated = service_record_service.update_claim_status(
        record.id, CLAIM_SUDAH, tanggal_klaim="2 agustus 2027"
    )
    assert updated.status_klaim == CLAIM_SUDAH
    assert updated.tanggal_klaim == date(2027, 8, 2)

    reverted = service_record_service.update_claim_status(record.id, CLAIM_BELUM)
    assert reverted.status_klaim == CLAIM_BELUM
    assert reverted.tanggal_klaim is None


def test_get_vehicle_service_history_not_found(service_record_service):
    with pytest.raises(NotFoundError):
        service_record_service.get_vehicle_service_history("ZZZZZZ")


def test_add_service_record_unknown_vehicle(service_record_service):
    with pytest.raises(NotFoundError):
        service_record_service.add_service_record(999999)


def test_invalid_quantity_rejected_without_persisting(vehicle, service_record_service, session):
    with pytest.raises(ValidationError):
        service_record_service.add_service_record(
            vehicle.id,
            parts=[{"nama_part": "Radiator", "jumlah": 0, "harga_satuan": 850000}],
        )
    assert session.query(ServiceRecord).count() == 0


def test_invalid_price_rejected_without_persisting(vehicle, service_record_service, session):
    with pytest.raises(ValidationError):
        service_record_service.add_service_record(
            vehicle.id,
            parts=[{"nama_part": "Radiator", "jumlah": 1, "harga_satuan": -1000}],
        )
    assert session.query(ServiceRecord).count() == 0


def test_add_service_record_rolls_back_on_commit_failure(
    vehicle, service_record_service, session, monkeypatch
):
    def failing_commit():
        raise IntegrityError("simulated failure", None, None)

    monkeypatch.setattr(session, "commit", failing_commit)

    with pytest.raises(ConflictError):
        service_record_service.add_service_record(
            vehicle.id,
            jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}],
            parts=[{"nama_part": "Filter oli", "jumlah": 1, "harga_satuan": 25000}],
        )

    # The service rolled back the whole transaction; nothing persisted.
    assert session.query(ServiceRecord).count() == 0


def test_record_service_visit_creates_vehicle_and_record(service_record_service, session):
    record = service_record_service.record_service_visit(
        nopol="B 3413 FED",
        nama_client="Dhani",
        jenis_mobil="Avanza",
        tahun_mobil=2021,
        jobs=[{"deskripsi": "ganti radiator", "jumlah": 1, "harga": 150000}],
        parts=[{"nama_part": "Radiator", "jumlah": 1, "harga_satuan": 850000}],
    )
    assert record.vehicle.nopol == "B3413FED"
    assert record.vehicle.nama_client == "Dhani"
    assert record.vehicle.jenis_mobil == "Avanza"
    assert record.vehicle.tahun_mobil == 2021
    assert record.total_servis == Decimal("1000000.00")
    assert session.query(Vehicle).count() == 1
    assert session.query(ServiceRecord).count() == 1


def test_record_service_visit_total_only(service_record_service, session):
    record = service_record_service.record_service_visit(
        nopol="B1234XYZ",
        nama_client="Budi",
        total_servis="600rb",
        jobs=[{"deskripsi": "ganti radiator"}],
    )
    assert record.total_servis == Decimal("600000.00")
    assert record.biaya_jasa is None
    assert record.total_part is None


def test_record_service_visit_existing_vehicle_no_duplicate(
    vehicle_service, service_record_service, session
):
    v = vehicle_service.create_vehicle(nama_client="Budi", nopol="B1234ABC")
    record = service_record_service.record_service_visit(
        nopol="b 1234 abc",
        jobs=[{"deskripsi": "ganti oli", "jumlah": 1, "harga": 50000}],
    )
    assert session.query(Vehicle).count() == 1
    assert record.vehicle.id == v.id
    assert session.query(ServiceRecord).count() == 1


def test_record_service_visit_name_optional(service_record_service, session):
    record = service_record_service.record_service_visit(
        nopol="B1234ABC",
        jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}],
    )
    assert record.vehicle.nama_client is None  # name is optional
    assert session.query(Vehicle).count() == 1
    assert session.query(ServiceRecord).count() == 1


def test_record_service_visit_rolls_back_on_failure(service_record_service, session):
    with pytest.raises(ValidationError):
        service_record_service.record_service_visit(
            nopol="B1234ABC",
            nama_client="Budi",
            parts=[{"nama_part": "Radiator", "jumlah": 0, "harga_satuan": 850000}],
        )
    assert session.query(Vehicle).count() == 0
    assert session.query(ServiceRecord).count() == 0
