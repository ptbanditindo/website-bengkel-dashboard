"""Deterministic tests for ReportingService (no AI/API calls)."""

from datetime import date, datetime
from decimal import Decimal

from services.reporting import ReportingService


def _seed(vehicle_service, service_record_service):
    v1 = vehicle_service.create_vehicle(
        nama_client="Budi", nopol="B1111AAA", jenis_mobil="Avanza", tahun_mobil=2021
    )
    v2 = vehicle_service.create_vehicle(
        nama_client="Dhani", nopol="B2222BBB", jenis_mobil="Xenia", tahun_mobil=2022
    )

    # Service 1 (known totals)
    service_record_service.add_service_record(
        v1.id,
        waktu_service=datetime(2026, 1, 5),
        jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}],
        parts=[{"nama_part": "Filter oli", "jumlah": 1, "harga_satuan": 25000}],
        garansi_sampai=date(2027, 1, 5),
    )
    # Service 2 (total-only, unknown breakdown)
    service_record_service.add_service_record(
        v1.id,
        waktu_service=datetime(2026, 2, 10),
        jobs=[{"deskripsi": "Ganti radiator"}],
        total_servis="600rb",
    )
    # Service 3 on v2
    service_record_service.add_service_record(
        v2.id,
        waktu_service=datetime(2026, 3, 1),
        jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}],
    )
    return v1, v2


def test_count_vehicles_and_records(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    r = ReportingService(session)
    assert r.count_vehicles() == 2
    assert r.count_service_records() == 3


def test_service_totals_all_known(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    data = ReportingService(session).service_totals()
    assert data["jumlah_servis"] == 3
    assert data["total_servis"] == Decimal("725000.00")  # 75000 + 600000 + 50000


def test_service_totals_unknown_becomes_none(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    # Add a record with unknown total (no price)
    v = vehicle_service.find_vehicle_by_plate("B1111AAA")
    service_record_service.add_service_record(
        v.id, waktu_service=datetime(2026, 4, 1), jobs=[{"deskripsi": "Cek kaki-kaki"}]
    )
    data = ReportingService(session).service_totals()
    assert data["total_servis"] is None
    assert data["jumlah_servis"] == 4


def test_period_summary(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    rows = ReportingService(session).period_summary()
    assert len(rows) == 3
    by_period = {r["periode"]: r for r in rows}
    assert by_period["2026-01"]["jumlah_servis"] == 1
    assert by_period["2026-01"]["total_servis"] == Decimal("75000.00")
    assert by_period["2026-02"]["total_servis"] == Decimal("600000.00")


def test_top_jobs(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    rows = ReportingService(session).top_jobs()
    assert rows[0]["deskripsi"] == "Ganti oli"
    assert rows[0]["jumlah"] == 2


def test_part_usage(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    rows = ReportingService(session).part_usage()
    assert rows == [{"nama_part": "Filter oli", "jumlah": 1, "jumlah_servis": 1}]


def test_vehicles_under_warranty(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    rows = ReportingService(session).vehicles_under_warranty(today=date(2026, 6, 1))
    assert [r["nopol"] for r in rows] == ["B1111AAA"]
    # expired warranty (today after end date) -> empty
    expired = ReportingService(session).vehicles_under_warranty(today=date(2028, 1, 1))
    assert expired == []


def test_activity_summary(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    data = ReportingService(session).activity_summary()
    assert data["jumlah_kendaraan"] == 2
    assert data["jumlah_servis"] == 3
    assert data["jumlah_pekerjaan"] == 3
    assert data["jumlah_part"] == 1
    assert data["total_servis"] == Decimal("725000.00")


def test_search_records_by_job(vehicle_service, service_record_service, session):
    _seed(vehicle_service, service_record_service)
    records = ReportingService(session).search_records_by_job("oli")
    assert len(records) == 2
    records = ReportingService(session).search_records_by_job("radiator")
    assert len(records) == 1
