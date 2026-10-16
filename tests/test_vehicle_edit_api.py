"""Targeted tests for the vehicle edit endpoint (H8D).

Full regression and combined integration are deferred to H8G.
"""

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
    api_app.app.dependency_overrides[real_get_db] = _get_db
    yield TestClient(api_app.app)
    api_app.app.dependency_overrides.pop(real_get_db, None)


@pytest.fixture()
def seeded(engine):
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    vs = VehicleService(s)
    srs = ServiceRecordService(s)
    v1 = vs.create_vehicle(nama_client="Budi", nopol="B1111AAA", jenis_mobil="Avanza", tahun_mobil=2021)
    v2 = vs.create_vehicle(nama_client="Dhani", nopol="B2222BBB")
    srs.add_service_record(v1.id, jobs=[{"deskripsi": "Ganti oli", "jumlah": 1, "harga": 50000}])
    s.close()
    return v1, v2


def test_edit_nama(seeded, client):
    v1, _ = seeded
    r = client.put(f"/api/vehicles/{v1.id}", json={"nama_client": "Budi Baru"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["nama_client"] == "Budi Baru"


def test_edit_wa(seeded, client):
    v1, _ = seeded
    r = client.put(f"/api/vehicles/{v1.id}", json={"nomor_wa": "0812345"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["nomor_wa"] == "0812345"


def test_edit_nopol_normalized(seeded, client):
    v1, _ = seeded
    r = client.put(f"/api/vehicles/{v1.id}", json={"nopol": "b 9999 xyz"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["nopol"] == "B9999XYZ"


def test_edit_nopol_duplicate_conflict(seeded, client):
    v1, v2 = seeded
    r = client.put(f"/api/vehicles/{v1.id}", json={"nopol": "B2222BBB"}, headers=AUTH)
    assert r.status_code == 409


def test_edit_not_found(seeded, client):
    r = client.put("/api/vehicles/9999", json={"nama_client": "X"}, headers=AUTH)
    assert r.status_code == 404


def test_edit_requires_auth(seeded, client):
    v1, _ = seeded
    assert client.put(f"/api/vehicles/{v1.id}", json={"nama_client": "X"}).status_code == 401


def test_edit_preserves_service_records(seeded, client, engine):
    v1, _ = seeded
    client.put(f"/api/vehicles/{v1.id}", json={"nama_client": "Budi Baru"}, headers=AUTH)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    assert s.query(ServiceRecord).count() == 1
    rec = s.query(ServiceRecord).one()
    assert rec.vehicle_id == v1.id
    assert rec.jobs[0].deskripsi == "Ganti oli"
    s.close()


def test_edit_invalid_tahun(seeded, client):
    v1, _ = seeded
    r = client.put(f"/api/vehicles/{v1.id}", json={"tahun_mobil": 1800}, headers=AUTH)
    assert r.status_code == 422


def test_edit_empty_body(seeded, client):
    v1, _ = seeded
    r = client.put(f"/api/vehicles/{v1.id}", json={}, headers=AUTH)
    assert r.status_code == 400
