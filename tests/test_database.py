"""Tahap A tests: schema, relations, constraints, timestamps, and rollback."""

import time
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from database.models import (
    CLAIM_BELUM,
    CLAIM_SUDAH,
    ServiceJob,
    ServicePart,
    ServiceRecord,
    Vehicle,
    normalize_plate,
)


# ---------------------------------------------------------------------------
# Plate normalization
# ---------------------------------------------------------------------------
def test_normalize_plate_uppercase_and_removes_spaces():
    assert normalize_plate("B 1234 ABC") == "B1234ABC"


def test_normalize_plate_lowercase():
    assert normalize_plate("b1234abc") == "B1234ABC"


def test_normalize_plate_strips_and_collapses_whitespace():
    assert normalize_plate("  b   1234   abc  ") == "B1234ABC"


def test_normalize_plate_empty_and_none():
    assert normalize_plate("") == ""
    assert normalize_plate(None) == ""


# ---------------------------------------------------------------------------
# Vehicle uniqueness & identity
# ---------------------------------------------------------------------------
def test_duplicate_plate_rejected(session):
    session.add(Vehicle(nama_client="Budi", nopol="B1234ABC"))
    session.commit()

    with pytest.raises(IntegrityError):
        session.add(Vehicle(nama_client="Andi", nopol="B1234ABC"))
        session.commit()
    session.rollback()

    assert session.query(Vehicle).count() == 1


def test_same_customer_multiple_vehicles(session):
    session.add(Vehicle(nama_client="Budi", nopol="B1111AAA"))
    session.add(Vehicle(nama_client="Budi", nopol="B2222BBB"))
    session.commit()

    vehicles = session.query(Vehicle).filter_by(nama_client="Budi").all()
    assert len(vehicles) == 2
    assert {v.nopol for v in vehicles} == {"B1111AAA", "B2222BBB"}


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------
def test_one_vehicle_many_service_records(session):
    vehicle = Vehicle(nama_client="Budi", nopol="B1234ABC")
    session.add(vehicle)
    session.commit()

    session.add_all([
        ServiceRecord(vehicle_id=vehicle.id),
        ServiceRecord(vehicle_id=vehicle.id),
    ])
    session.commit()

    loaded = session.query(Vehicle).filter_by(nopol="B1234ABC").one()
    assert len(loaded.service_records) == 2


def test_service_multiple_jobs_and_parts(session):
    vehicle = Vehicle(nama_client="Budi", nopol="B1234ABC")
    session.add(vehicle)
    session.commit()

    record = ServiceRecord(vehicle_id=vehicle.id)
    record.jobs.append(ServiceJob(deskripsi="Pasang radiator", jumlah=1, harga=Decimal("150000")))
    record.jobs.append(ServiceJob(deskripsi="Ganti oli", jumlah=1, harga=Decimal("50000")))
    record.parts.append(ServicePart(nama_part="Radiator", jumlah=1, harga_satuan=Decimal("850000")))
    record.parts.append(ServicePart(nama_part="Air radiator", jumlah=2, harga_satuan=Decimal("50000")))
    session.add(record)
    session.commit()

    loaded = session.query(ServiceRecord).filter_by(id=record.id).one()
    assert len(loaded.jobs) == 2
    assert len(loaded.parts) == 2
    assert {j.deskripsi for j in loaded.jobs} == {"Pasang radiator", "Ganti oli"}
    assert {p.nama_part for p in loaded.parts} == {"Radiator", "Air radiator"}


def test_vehicle_service_records_relationship_via_parent(session):
    vehicle = Vehicle(nama_client="Budi", nopol="B1234ABC")
    record = ServiceRecord(vehicle=vehicle)
    session.add(record)
    session.commit()

    loaded = session.query(ServiceRecord).filter_by(id=record.id).one()
    assert loaded.vehicle_id == vehicle.id
    assert loaded.vehicle.nopol == "B1234ABC"


# ---------------------------------------------------------------------------
# Foreign keys & referential integrity
# ---------------------------------------------------------------------------
def test_foreign_keys_are_enabled(session):
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_foreign_key_enforced(session):
    with pytest.raises(IntegrityError):
        session.add(ServiceRecord(vehicle_id=999999))
        session.commit()
    session.rollback()


def test_vehicle_with_service_records_cannot_be_deleted(session):
    vehicle = Vehicle(nama_client="Budi", nopol="B1234ABC")
    session.add(vehicle)
    session.commit()
    session.add(ServiceRecord(vehicle_id=vehicle.id))
    session.commit()

    # RESTRICT prevents deleting a vehicle that still has service records.
    with pytest.raises(IntegrityError):
        session.execute(text("DELETE FROM vehicles WHERE id = :id"), {"id": vehicle.id})
        session.commit()
    session.rollback()

    assert session.query(Vehicle).filter_by(id=vehicle.id).count() == 1


# ---------------------------------------------------------------------------
# Warranty fields
# ---------------------------------------------------------------------------
def test_warranty_defaults_and_nullable(session):
    vehicle = Vehicle(nama_client="Budi", nopol="B1234ABC")
    session.add(vehicle)
    session.commit()

    r1 = ServiceRecord(vehicle_id=vehicle.id, garansi_sampai=date(2027, 1, 14))
    r2 = ServiceRecord(vehicle_id=vehicle.id)  # no warranty date
    session.add_all([r1, r2])
    session.commit()

    assert r1.garansi_sampai == date(2027, 1, 14)
    assert r1.status_klaim == CLAIM_BELUM
    assert r2.garansi_sampai is None
    assert r2.status_klaim == CLAIM_BELUM


def test_status_klaim_can_be_updated(session):
    vehicle = Vehicle(nama_client="Budi", nopol="B1234ABC")
    session.add(vehicle)
    session.commit()
    record = ServiceRecord(vehicle_id=vehicle.id)
    session.add(record)
    session.commit()

    record.status_klaim = CLAIM_SUDAH
    session.commit()

    loaded = session.query(ServiceRecord).filter_by(id=record.id).one()
    assert loaded.status_klaim == CLAIM_SUDAH


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def test_timestamps_are_set_on_insert(session):
    vehicle = Vehicle(nama_client="Budi", nopol="B1234ABC")
    session.add(vehicle)
    session.commit()

    assert vehicle.created_at is not None
    assert vehicle.updated_at is not None


def test_updated_at_changes_on_update(session):
    vehicle = Vehicle(nama_client="Budi", nopol="B1234ABC")
    session.add(vehicle)
    session.commit()
    original = vehicle.updated_at

    time.sleep(0.02)
    vehicle.nama_client = "Budi (diperbarui)"
    session.commit()

    assert vehicle.updated_at > original


# ---------------------------------------------------------------------------
# Rollback on failure
# ---------------------------------------------------------------------------
def test_rollback_on_failure_persists_nothing(session):
    vehicle = Vehicle(nama_client="Budi", nopol="B1234ABC")
    session.add(vehicle)
    session.commit()

    with pytest.raises(IntegrityError):
        session.add(ServiceRecord(vehicle_id=999999))
        session.commit()
    session.rollback()

    assert session.query(ServiceRecord).count() == 0
    assert session.query(Vehicle).count() == 1


# ---------------------------------------------------------------------------
# init_db (creates directory + tables, non-destructive)
# ---------------------------------------------------------------------------
def test_init_db_creates_directory_and_tables(tmp_path):
    from database.session import init_db

    db_file = tmp_path / "nested" / "workshop.db"
    url = f"sqlite:///{db_file.as_posix()}"

    init_db(url)

    assert db_file.parent.exists()
    assert db_file.exists()

    eng = create_engine(url)
    try:
        tables = set(inspect(eng).get_table_names())
    finally:
        eng.dispose()

    assert {"vehicles", "service_records", "service_jobs", "service_parts"} <= tables


# ---------------------------------------------------------------------------
# SQLite connection pragmas (H8B): busy_timeout on new connections, WAL helper
# ---------------------------------------------------------------------------
def test_sqlite_busy_timeout_applied(tmp_path):
    from database.session import _build_engine

    eng = _build_engine(f"sqlite:///{(tmp_path / 'pragmas.db').as_posix()}")
    with eng.connect() as conn:
        busy = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
        fk = conn.exec_driver_sql("PRAGMA foreign_keys").scalar()
    eng.dispose()
    assert int(busy) == 5000
    assert int(fk) == 1


def test_enable_wal_on_temp_db(tmp_path):
    from database.session import _build_engine, enable_wal

    eng = _build_engine(f"sqlite:///{(tmp_path / 'wal.db').as_posix()}")
    enable_wal(eng)
    with eng.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
    eng.dispose()
    assert str(mode).lower() == "wal"


# ---------------------------------------------------------------------------
# Schema indexes & unique constraints
# ---------------------------------------------------------------------------
def test_schema_has_unique_nopol_and_fk_indexes(engine):
    insp = inspect(engine)

    vehicle_uniques = insp.get_unique_constraints("vehicles")
    assert any("nopol" in uq.get("column_names", []) for uq in vehicle_uniques)

    sr_indexes = {tuple(ix["column_names"]) for ix in insp.get_indexes("service_records")}
    assert ("vehicle_id",) in sr_indexes

    sj_indexes = {tuple(ix["column_names"]) for ix in insp.get_indexes("service_jobs")}
    assert ("service_record_id",) in sj_indexes

    sp_indexes = {tuple(ix["column_names"]) for ix in insp.get_indexes("service_parts")}
    assert ("service_record_id",) in sp_indexes

