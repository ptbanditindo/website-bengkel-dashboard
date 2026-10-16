"""End-to-end integration test chaining H8A–H8E on a temporary file database."""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import api.app as api_app
from database.base import Base
import database.models  # noqa: F401
from database.session import _build_engine, get_db as real_get_db
from services.service_record_service import ServiceRecordService
from services.vehicle_service import VehicleService

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def integrated(tmp_path, monkeypatch):
    db_file = tmp_path / "it.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    eng = _build_engine(db_url)
    Base.metadata.create_all(eng)

    # backup validation requires an alembic_version table.
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("INSERT INTO alembic_version (version_num) VALUES ('fa7fa27bbb86')")
    conn.commit()
    conn.close()

    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)

    def _get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(api_app, "init_db", lambda: None)
    monkeypatch.setenv("UI_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(api_app, "get_database_url", lambda: db_url)
    # Keep get_db and the restore endpoint's db_engine.dispose() on the same temp engine.
    monkeypatch.setattr(api_app, "db_engine", eng)
    api_app.app.dependency_overrides[real_get_db] = _get_db

    # Seed one vehicle + one service record.
    s = factory()
    v = VehicleService(s).create_vehicle(nama_client="Budi", nopol="B1111AAA")
    ServiceRecordService(s).add_service_record(v.id, jobs=[{"deskripsi": "Ganti oli", "harga": 50000}])
    s.close()

    yield TestClient(api_app.app), db_file, v.id

    api_app.app.dependency_overrides.pop(real_get_db, None)
    eng.dispose()


def test_read_edit_backup_restore_chain(integrated):
    client, db_file, vehicle_id = integrated

    # 1. Read.
    r = client.get("/api/vehicles", headers=AUTH)
    assert r.status_code == 200 and len(r.json()) == 1

    # 2. Edit (partial: only nama_client).
    r = client.put(f"/api/vehicles/{vehicle_id}", json={"nama_client": "Budi Edit"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["nama_client"] == "Budi Edit"

    # 3. Verify detail + search.
    assert client.get(f"/api/vehicles/{vehicle_id}", headers=AUTH).json()["nama_client"] == "Budi Edit"
    assert client.get("/api/vehicles/search?q=b 1111 aaa", headers=AUTH).json()[0]["nopol"] == "B1111AAA"

    # 4. Service record intact.
    recs = client.get(f"/api/vehicles/{vehicle_id}/service-records", headers=AUTH).json()
    assert len(recs) == 1 and recs[0]["jobs"][0]["deskripsi"] == "Ganti oli"

    # 5. Backup.
    import os
    from pathlib import Path

    meta = client.post("/api/admin/backup", headers=AUTH).json()
    backup_path = Path(os.environ["BACKUP_DIR"]) / meta["filename"]
    backup_bytes = backup_path.read_bytes()

    # 6. Modify data after backup.
    client.put(f"/api/vehicles/{vehicle_id}", json={"nama_client": "Budi Lagi"}, headers=AUTH)
    assert client.get(f"/api/vehicles/{vehicle_id}", headers=AUTH).json()["nama_client"] == "Budi Lagi"

    # 7. Restore the backup.
    r = client.post("/api/admin/restore", content=backup_bytes, headers=AUTH)
    assert r.status_code == 200

    # 8. Verify restore (back to "Budi Edit").
    assert client.get(f"/api/vehicles/{vehicle_id}", headers=AUTH).json()["nama_client"] == "Budi Edit"

    # 9. Operational DB untouched: the temp DB still has one vehicle.
    conn = sqlite3.connect(str(db_file))
    n = conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
    conn.close()
    assert n == 1
