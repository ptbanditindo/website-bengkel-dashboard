"""Targeted tests for backup & restore (H8E).

Full regression deferred to H8G. Uses temp databases; never touches data/workshop.db.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

import api.app as api_app
from services import backup as backup


def _make_db(tmp_path, filename="test.db"):
    from database.base import Base
    from database.session import _build_engine
    import database.models  # noqa: F401  (register models)

    db_file = tmp_path / filename
    eng = _build_engine(f"sqlite:///{db_file.as_posix()}")
    Base.metadata.create_all(eng)
    eng.dispose()

    # validate_backup_file also requires an alembic_version table.
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
    conn.execute("INSERT OR REPLACE INTO alembic_version (version_num) VALUES ('fa7fa27bbb86')")
    conn.commit()
    conn.close()
    return f"sqlite:///{db_file.as_posix()}", db_file


def _seed_vehicle(db_file, nopol, nama="Budi"):
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO vehicles (nama_client, nomor_wa, nopol, jenis_mobil, tahun_mobil, alamat_client, created_at, updated_at) "
        "VALUES (?, NULL, ?, NULL, NULL, NULL, '2026-01-01 00:00:00', '2026-01-01 00:00:00')",
        (nama, nopol),
    )
    conn.commit()
    conn.close()


def _vehicle_nopols(db_file):
    conn = sqlite3.connect(str(db_file))
    rows = [r[0] for r in conn.execute("SELECT nopol FROM vehicles ORDER BY nopol")]
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
def test_create_backup_creates_valid_db(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    url, db_file = _make_db(tmp_path)
    _seed_vehicle(db_file, "B1111AAA", "Budi")

    result = backup.create_backup(url)
    backup_file = tmp_path / "backups" / result["filename"]
    assert backup_file.exists()
    assert result["size"] > 0

    conn = sqlite3.connect(str(backup_file))
    assert conn.execute("SELECT nopol FROM vehicles").fetchone()[0] == "B1111AAA"
    conn.close()


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
def test_validate_backup_accepts_valid(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    url, db_file = _make_db(tmp_path)
    _seed_vehicle(db_file, "B1111AAA")
    meta = backup.create_backup(url)
    backup.validate_backup_file(tmp_path / "backups" / meta["filename"])  # no raise


def test_validate_backup_rejects_corrupt(tmp_path):
    f = tmp_path / "corrupt.db"
    f.write_text("this is not sqlite")
    with pytest.raises(backup.BackupError):
        backup.validate_backup_file(f)


def test_validate_backup_rejects_incompatible(tmp_path):
    f = tmp_path / "wrong.db"
    conn = sqlite3.connect(str(f))
    conn.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    with pytest.raises(backup.BackupError):
        backup.validate_backup_file(f)


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
def test_restore_replaces_data(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    url, db_file = _make_db(tmp_path)
    _seed_vehicle(db_file, "B1111AAA", "Budi")

    meta = backup.create_backup(url)
    backup_bytes = (tmp_path / "backups" / meta["filename"]).read_bytes()

    _seed_vehicle(db_file, "B2222BBB", "Dhani")  # add another vehicle
    assert _vehicle_nopols(db_file) == ["B1111AAA", "B2222BBB"]

    backup.restore_from_file(url, backup_bytes)

    assert _vehicle_nopols(db_file) == ["B1111AAA"]  # back to pre-restore state


def test_restore_rejects_invalid_keeps_active(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    url, db_file = _make_db(tmp_path)
    _seed_vehicle(db_file, "B1111AAA", "Budi")

    with pytest.raises(backup.BackupError):
        backup.restore_from_file(url, b"not a sqlite database")

    assert _vehicle_nopols(db_file) == ["B1111AAA"]  # unchanged


# ---------------------------------------------------------------------------
# Endpoint auth
# ---------------------------------------------------------------------------
def test_admin_endpoints_require_auth(monkeypatch):
    monkeypatch.setattr(api_app, "init_db", lambda: None)
    monkeypatch.setenv("UI_ACCESS_TOKEN", "test-token")
    client = TestClient(api_app.app)
    assert client.post("/api/admin/backup").status_code == 401
    assert client.post("/api/admin/restore", content=b"x").status_code == 401
