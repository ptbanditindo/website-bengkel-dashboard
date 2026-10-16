"""Tests for the VehicleService (Tahap B)."""

import pytest

from database.models import ServiceRecord
from services.exceptions import ConflictError, NotFoundError, ValidationError


def test_create_vehicle(vehicle_service):
    v = vehicle_service.create_vehicle(
        nama_client="Budi", nopol="B 1234 ABC", tahun_mobil=2020, jenis_mobil="Toyota Avanza"
    )
    assert v.id is not None
    assert v.nopol == "B1234ABC"
    assert v.nama_client == "Budi"
    assert v.tahun_mobil == 2020


def test_create_vehicle_normalizes_plate(vehicle_service):
    v = vehicle_service.create_vehicle(nama_client="Budi", nopol="  b 1234 abc ")
    assert v.nopol == "B1234ABC"


def test_create_vehicle_requires_plate_only(vehicle_service):
    # Name is optional; only the plate is required.
    v = vehicle_service.create_vehicle(nama_client=None, nopol="B1234ABC")
    assert v.nama_client is None
    with pytest.raises(ValidationError):
        vehicle_service.create_vehicle(nama_client="Budi", nopol="")


def test_duplicate_plate_rejected(vehicle_service):
    vehicle_service.create_vehicle(nama_client="Budi", nopol="B1234ABC")
    with pytest.raises(ConflictError):
        vehicle_service.create_vehicle(nama_client="Andi", nopol="B 1234 ABC")


def test_find_by_plate_is_case_and_space_insensitive(vehicle_service):
    vehicle_service.create_vehicle(nama_client="Budi", nopol="B1234ABC")
    found = vehicle_service.find_vehicle_by_plate("b 1234 abc")
    assert found is not None
    assert found.nama_client == "Budi"


def test_get_vehicle_not_found(vehicle_service):
    with pytest.raises(NotFoundError):
        vehicle_service.get_vehicle(999999)


def test_list_vehicles(vehicle_service):
    vehicle_service.create_vehicle(nama_client="Budi", nopol="B1111AAA")
    vehicle_service.create_vehicle(nama_client="Budi", nopol="B2222BBB")
    vehicles = vehicle_service.list_vehicles()
    assert len(vehicles) == 2


def test_update_vehicle_fields(vehicle_service):
    v = vehicle_service.create_vehicle(nama_client="Budi", nopol="B1234ABC", tahun_mobil=2020)
    updated = vehicle_service.update_vehicle(v.id, nama_client="Budi Update", tahun_mobil=2021)
    assert updated.nama_client == "Budi Update"
    assert updated.tahun_mobil == 2021
    assert updated.nopol == "B1234ABC"  # unchanged


def test_update_vehicle_plate_conflict(vehicle_service):
    v1 = vehicle_service.create_vehicle(nama_client="Budi", nopol="B1111AAA")
    vehicle_service.create_vehicle(nama_client="Andi", nopol="B2222BBB")
    with pytest.raises(ConflictError):
        vehicle_service.update_vehicle(v1.id, nopol="B2222BBB")


def test_delete_vehicle_without_records(vehicle_service):
    v = vehicle_service.create_vehicle(nama_client="Budi", nopol="B1234ABC")
    vehicle_service.delete_vehicle(v.id)
    assert vehicle_service.find_vehicle_by_plate("B1234ABC") is None


def test_delete_vehicle_with_records_rejected(vehicle_service, service_record_service):
    v = vehicle_service.create_vehicle(nama_client="Budi", nopol="B1234ABC")
    service_record_service.add_service_record(
        v.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}]
    )
    with pytest.raises(ConflictError):
        vehicle_service.delete_vehicle(v.id)


def test_update_vehicle_keeps_service_records(vehicle_service, service_record_service, session):
    v = vehicle_service.create_vehicle(nama_client="Budi", nopol="B1234ABC")
    service_record_service.add_service_record(
        v.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}]
    )

    updated = vehicle_service.update_vehicle(v.id, nama_client="Budi Baru", nomor_wa="08123")
    assert updated.nama_client == "Budi Baru"
    assert updated.nomor_wa == "08123"
    assert session.query(ServiceRecord).count() == 1  # history preserved
    assert session.query(ServiceRecord).one().vehicle_id == v.id
