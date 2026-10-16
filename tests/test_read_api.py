"""Tests for the read-only API endpoints (H8C).

Uses the in-memory engine from conftest; never touches data/workshop.db.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import api.app as api_app
from database.models import ServiceRecord, Vehicle
from services.service_record_service import ServiceRecordService
from services.vehicle_service import VehicleService

TOKEN = "test-ui-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(engine, monkeypatch):
    from database.session import get_db as real_get_db

    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(api_app, "init_db", lambda: None)
    monkeypatch.setenv("UI_ACCESS_TOKEN", TOKEN)
    # Override the get_db dependency so endpoints use the in-memory engine.
    api_app.app.dependency_overrides[real_get_db] = _get_db
    yield TestClient(api_app.app)
    api_app.app.dependency_overrides.pop(real_get_db, None)


@pytest.fixture()
def seeded(engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    vs = VehicleService(s)
    srs = ServiceRecordService(s)
    v1 = vs.create_vehicle(
        nama_client="Budi", nopol="B1111AAA", jenis_mobil="Avanza", tahun_mobil=2021,
        nomor_wa="0811", alamat_client="Jakarta",
    )
    srs.add_service_record(
        v1.id, waktu_service=datetime(2026, 1, 5),
        jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}],
    )
    # Incomplete vehicle (no client data) created via record_service_visit.
    rec2 = srs.record_service_visit(
        nopol="B2222BBB", waktu_service=datetime(2026, 2, 10),
        jobs=[{"deskripsi": "Ganti radiator"}], total_servis="600rb",
    )
    v2 = rec2.vehicle
    s.close()
    return v1, v2


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def test_dashboard_counts(seeded, client):
    r = client.get("/api/dashboard", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["vehicle_count"] == 2
    assert data["service_record_count"] == 2
    assert data["incomplete_vehicles_count"] == 1  # only B2222BBB is incomplete
    assert len(data["recent_service_records"]) == 2
    # newest first (2026-02-10 = B2222BBB)
    assert data["recent_service_records"][0]["nopol"] == "B2222BBB"
    assert data["recent_service_records"][0]["nama_client"] is None
    assert data["recent_service_records"][1]["nopol"] == "B1111AAA"


def test_dashboard_empty(client):
    r = client.get("/api/dashboard", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["vehicle_count"] == 0
    assert data["service_record_count"] == 0
    assert data["incomplete_vehicles_count"] == 0
    assert data["recent_service_records"] == []


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
def test_vehicles_list(seeded, client):
    r = client.get("/api/vehicles", headers=AUTH)
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_vehicles_pagination(seeded, client):
    r = client.get("/api/vehicles?limit=1&offset=0", headers=AUTH)
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_vehicles_invalid_limit(seeded, client):
    assert client.get("/api/vehicles?limit=0", headers=AUTH).status_code == 400
    assert client.get("/api/vehicles?limit=999", headers=AUTH).status_code == 400
    assert client.get("/api/vehicles?offset=-1", headers=AUTH).status_code == 400


def test_vehicles_search_normalized_plate(seeded, client):
    r = client.get("/api/vehicles/search?q=b 1111 aaa", headers=AUTH)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["nopol"] == "B1111AAA"


def test_vehicle_detail_found(seeded, client):
    v1, _ = seeded
    r = client.get(f"/api/vehicles/{v1.id}", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["nopol"] == "B1111AAA"
    assert data["nama_client"] == "Budi"
    assert "nama_client" not in data["missing_fields"]
    assert data["service_record_count"] == 1


def test_vehicle_detail_incomplete(seeded, client):
    _, v2 = seeded
    r = client.get(f"/api/vehicles/{v2.id}", headers=AUTH)
    data = r.json()
    assert set(data["missing_fields"]) == {"nama_client", "nomor_wa", "jenis_mobil", "tahun_mobil", "alamat_client"}


def test_vehicle_detail_not_found(seeded, client):
    assert client.get("/api/vehicles/9999", headers=AUTH).status_code == 404


# ---------------------------------------------------------------------------
# Service records
# ---------------------------------------------------------------------------
def test_service_records_for_vehicle(seeded, client):
    v1, _ = seeded
    r = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    rec = data[0]
    assert rec["jobs"][0]["deskripsi"] == "Ganti oli"
    assert rec["jobs"][0]["harga"] == "50000.00"  # Decimal serialized as string
    assert rec["total_servis"] == "50000.00"


def test_service_record_detail_total_only(seeded, client):
    _, v2 = seeded
    recs = client.get(f"/api/vehicles/{v2.id}/service-records", headers=AUTH).json()
    rec_id = recs[0]["id"]
    detail = client.get(f"/api/service-records/{rec_id}", headers=AUTH).json()
    assert detail["total_servis"] == "600000.00"
    assert detail["biaya_jasa"] is None  # total-only keeps breakdown unknown
    assert detail["total_part"] is None
    assert detail["parts"] == []
    assert detail["waktu_service"].startswith("2026-02-10")


def test_service_records_vehicle_not_found(seeded, client):
    assert client.get("/api/vehicles/9999/service-records", headers=AUTH).status_code == 404


def test_service_record_not_found(seeded, client):
    assert client.get("/api/service-records/9999", headers=AUTH).status_code == 404


def test_service_records_not_mixed_across_vehicles(seeded, client):
    v1, v2 = seeded
    recs1 = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    recs2 = client.get(f"/api/vehicles/{v2.id}/service-records", headers=AUTH).json()
    assert [r["jobs"][0]["deskripsi"] for r in recs1] == ["Ganti oli"]
    assert [r["jobs"][0]["deskripsi"] for r in recs2] == ["Ganti radiator"]


# ---------------------------------------------------------------------------
# Security & integrity
# ---------------------------------------------------------------------------
def test_all_data_endpoints_protected(seeded, client):
    paths = [
        "/api/dashboard",
        "/api/vehicles",
        "/api/vehicles/search?q=x",
        "/api/vehicles/1",
        "/api/vehicles/1/service-records",
        "/api/service-records/1",
    ]
    for path in paths:
        assert client.get(path).status_code == 401, path


def test_read_endpoints_do_not_mutate(seeded, client, engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    before_v = s.query(Vehicle).count()
    before_s = s.query(ServiceRecord).count()
    s.close()

    client.get("/api/dashboard", headers=AUTH)
    client.get("/api/vehicles", headers=AUTH)
    client.get("/api/vehicles/search?q=x", headers=AUTH)

    s = factory()
    assert s.query(Vehicle).count() == before_v
    assert s.query(ServiceRecord).count() == before_s
    s.close()


# ---------------------------------------------------------------------------
# Price editing (service jobs / parts)
# ---------------------------------------------------------------------------
def test_update_job_price_recomputes_totals(seeded, client):
    v1, _ = seeded
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    job_id = recs[0]["jobs"][0]["id"]
    r = client.put(f"/api/service-jobs/{job_id}", json={"harga": "75000"}, headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["jobs"][0]["id"] == job_id
    assert data["jobs"][0]["harga"] == "75000.00"
    assert data["jobs"][0]["subtotal"] == "75000.00"
    assert data["biaya_jasa"] == "75000.00"
    assert data["total_part"] == "0.00"
    assert data["total_servis"] == "75000.00"


def test_update_part_price_recomputes_totals(seeded, client, engine):
    v1, _ = seeded
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    srs = ServiceRecordService(s)
    record = srs.add_service_record(
        v1.id,
        jobs=[{"deskripsi": "Pasang part", "jumlah": 1, "harga": 100000}],
        parts=[{"nama_part": "Busi", "jumlah": 2, "harga_satuan": 50000}],
    )
    part_id = record.parts[0].id
    s.close()

    r = client.put(f"/api/service-parts/{part_id}", json={"harga_satuan": "60000"}, headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    part = next(p for p in data["parts"] if p["id"] == part_id)
    assert part["harga_satuan"] == "60000.00"
    assert part["subtotal"] == "120000.00"
    assert data["biaya_jasa"] == "100000.00"
    assert data["total_part"] == "120000.00"
    assert data["total_servis"] == "220000.00"


def test_update_price_not_found(seeded, client):
    assert client.put("/api/service-jobs/9999", json={"harga": "100"}, headers=AUTH).status_code == 404
    assert client.put("/api/service-parts/9999", json={"harga_satuan": "100"}, headers=AUTH).status_code == 404


def test_update_price_invalid(seeded, client):
    v1, _ = seeded
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    job_id = recs[0]["jobs"][0]["id"]
    r = client.put(f"/api/service-jobs/{job_id}", json={"harga": "abc"}, headers=AUTH)
    assert r.status_code == 422


def test_update_price_endpoints_protected(seeded, client):
    assert client.put("/api/service-jobs/1", json={"harga": "100"}).status_code == 401
    assert client.put("/api/service-parts/1", json={"harga_satuan": "100"}).status_code == 401


def test_add_job_to_record_recomputes_totals(seeded, client):
    v1, _ = seeded
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    rec_id = recs[0]["id"]
    r = client.post(
        f"/api/service-records/{rec_id}/jobs",
        json={"deskripsi": "Cek rem", "jumlah": 2, "harga": "30000"},
        headers=AUTH,
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["jobs"]) == 2
    assert data["biaya_jasa"] == "110000.00"
    assert data["total_servis"] == "110000.00"


def test_add_part_to_record_recomputes_totals(seeded, client):
    v1, _ = seeded
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    rec_id = recs[0]["id"]
    r = client.post(
        f"/api/service-records/{rec_id}/parts",
        json={"nama_part": "Busi", "jumlah": 4, "harga_satuan": "25000"},
        headers=AUTH,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total_part"] == "100000.00"
    assert data["biaya_jasa"] == "50000.00"
    assert data["total_servis"] == "150000.00"
    assert data["parts"][0]["nama_part"] == "Busi"
    assert data["parts"][0]["subtotal"] == "100000.00"


def test_add_line_item_validation_and_auth(seeded, client):
    v1, _ = seeded
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    rec_id = recs[0]["id"]
    # missing required field -> 422
    assert client.post(f"/api/service-records/{rec_id}/jobs", json={"jumlah": 1}, headers=AUTH).status_code == 422
    # invalid price -> 422
    assert client.post(f"/api/service-records/{rec_id}/parts", json={"nama_part": "X", "harga_satuan": "abc"}, headers=AUTH).status_code == 422
    # record not found -> 404
    assert client.post("/api/service-records/9999/parts", json={"nama_part": "X"}, headers=AUTH).status_code == 404
    # requires auth -> 401
    assert client.post(f"/api/service-records/{rec_id}/parts", json={"nama_part": "X"}).status_code == 401


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------
def test_stock_crud(seeded, client):
    r = client.post("/api/stock", json={"nama": "Oli Mesin", "harga_modal": "50000", "harga_jual": "75000"}, headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["nama"] == "Oli Mesin"
    assert data["keuntungan"] == "25000.00"
    item_id = data["id"]

    r = client.get("/api/stock", headers=AUTH)
    assert any(s["nama"] == "Oli Mesin" for s in r.json())

    r = client.put(f"/api/stock/{item_id}", json={"harga_jual": "80000"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["keuntungan"] == "30000.00"

    assert client.delete(f"/api/stock/{item_id}", headers=AUTH).status_code == 200
    assert client.get("/api/stock", headers=AUTH).json() == []


def test_stock_auth_and_validation(seeded, client):
    assert client.get("/api/stock").status_code == 401
    assert client.post("/api/stock", json={"nama": "X"}).status_code == 401
    assert client.post("/api/stock", json={"harga_modal": "100"}, headers=AUTH).status_code == 422
    assert client.post("/api/stock", json={"nama": "X", "harga_modal": "abc"}, headers=AUTH).status_code == 422


def test_delete_referenced_stock_conflict(seeded, client):
    st = client.post(
        "/api/stock",
        json={"nama": "Oli Khusus", "harga_modal": "10000", "harga_jual": "15000", "jumlah": 5},
        headers=AUTH,
    ).json()
    v1, _ = seeded
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    rec_id = recs[0]["id"]
    client.post(
        f"/api/service-records/{rec_id}/parts",
        json={"nama_part": "Oli Khusus", "jumlah": 1, "harga_satuan": "15000", "stock_item_id": st["id"]},
        headers=AUTH,
    )
    r = client.delete(f"/api/stock/{st['id']}", headers=AUTH)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Profit, recent, create/delete record, claim
# ---------------------------------------------------------------------------
def test_dashboard_profit(seeded, client):
    r = client.get("/api/dashboard/profit?period=all", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert "keuntungan_jasa" in data
    assert "keuntungan_barang" in data
    assert client.get("/api/dashboard/profit?period=bogus", headers=AUTH).status_code == 400
    assert client.get("/api/dashboard/profit").status_code == 401


def test_recent_service_records(seeded, client):
    r = client.get("/api/service-records/recent?limit=10", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert "nopol" in data[0]


def test_create_and_delete_service_record(seeded, client):
    v1, _ = seeded
    r = client.post(f"/api/vehicles/{v1.id}/service-records", json={"waktu_service": "2026-03-01", "catatan": "Tes"}, headers=AUTH)
    assert r.status_code == 200
    rec_id = r.json()["id"]
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    assert any(x["id"] == rec_id for x in recs)
    assert client.delete(f"/api/service-records/{rec_id}", headers=AUTH).status_code == 200
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    assert all(x["id"] != rec_id for x in recs)


def test_claim_status_toggle(seeded, client):
    v1, _ = seeded
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    rec_id = recs[0]["id"]
    r = client.put(f"/api/service-records/{rec_id}/claim", json={"status_klaim": "Sudah claim"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status_klaim"] == "Sudah claim"
    assert client.put(f"/api/service-records/{rec_id}/claim", json={"status_klaim": "bogus"}, headers=AUTH).status_code == 422
    assert client.put(f"/api/service-records/{rec_id}/claim", json={"status_klaim": "Sudah claim"}).status_code == 401


def test_incomplete_warranty_endpoint(seeded, client):
    r = client.get("/api/service-records/incomplete-warranty", headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert all(x["bergaransi"] is None for x in data)


def test_claim_with_tanggal_klaim(seeded, client):
    v1, _ = seeded
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    rec_id = recs[0]["id"]
    r = client.put(
        f"/api/service-records/{rec_id}/claim",
        json={"status_klaim": "Sudah claim", "tanggal_klaim": "2 agustus 2027"},
        headers=AUTH,
    )
    assert r.status_code == 200
    assert r.json()["status_klaim"] == "Sudah claim"
    assert r.json()["tanggal_klaim"] == "2027-08-02"


def test_stock_with_kode_and_jumlah(seeded, client):
    r = client.post("/api/stock", json={"kode": "OLI-001", "nama": "Oli Mesin", "jumlah": 10, "harga_modal": "50000", "harga_jual": "75000"}, headers=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert data["kode"] == "OLI-001"
    assert data["jumlah"] == 10
    # duplicate kode -> 409
    assert client.post("/api/stock", json={"kode": "OLI-001", "nama": "Oli Lain"}, headers=AUTH).status_code == 409


def test_harga_jasa_crud(seeded, client):
    r = client.post("/api/harga-jasa", json={"nama": "Ganti oli", "keuntungan": "50000"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["nama"] == "Ganti oli"
    item_id = r.json()["id"]
    assert client.put(f"/api/harga-jasa/{item_id}", json={"keuntungan": "60000"}, headers=AUTH).status_code == 200
    assert client.delete(f"/api/harga-jasa/{item_id}", headers=AUTH).status_code == 200
    assert client.get("/api/harga-jasa", headers=AUTH).json() == []
    assert client.get("/api/harga-jasa").status_code == 401


def test_part_deducts_and_restores_stock(seeded, client):
    r = client.post("/api/stock", json={"kode": "UP-1", "nama": "Uppertank", "jumlah": 5, "harga_modal": "100000", "harga_jual": "150000"}, headers=AUTH)
    stock_id = r.json()["id"]
    v1, _ = seeded
    recs = client.get(f"/api/vehicles/{v1.id}/service-records", headers=AUTH).json()
    rec_id = recs[0]["id"]
    r = client.post(f"/api/service-records/{rec_id}/parts", json={"nama_part": "Uppertank", "jumlah": 2, "harga_satuan": "150000", "stock_item_id": stock_id}, headers=AUTH)
    assert r.status_code == 200
    stock = [s for s in client.get("/api/stock", headers=AUTH).json() if s["id"] == stock_id][0]
    assert stock["jumlah"] == 3
    assert client.delete(f"/api/service-records/{rec_id}", headers=AUTH).status_code == 200
    stock = [s for s in client.get("/api/stock", headers=AUTH).json() if s["id"] == stock_id][0]
    assert stock["jumlah"] == 5


def test_list_all_service_records_and_profit_history(seeded, client):
    r = client.get("/api/service-records?limit=500", headers=AUTH)
    assert r.status_code == 200
    assert len(r.json()) >= 1
    r = client.get("/api/profit/history?kind=barang&period=all", headers=AUTH)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert client.get("/api/profit/history?kind=bogus", headers=AUTH).status_code == 400

