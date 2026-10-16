"""Tests for WhatsApp DB backup/restore (on a temporary database)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.backup import backup_dir
from whatsapp import backup as wa_backup
from whatsapp.models import WaContact, WhatsAppBase


def test_backup_restore_whatsapp(monkeypatch, tmp_path):
    db_file = tmp_path / "wa.db"
    monkeypatch.setenv("WHATSAPP_DB_URL", "sqlite:///" + str(db_file))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))

    eng = create_engine("sqlite:///" + str(db_file))
    WhatsAppBase.metadata.create_all(eng)
    s = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)()
    s.add(WaContact(wa_number="0812-1", nama="Budi"))
    s.commit()
    s.close()
    eng.dispose()

    meta = wa_backup.create_backup()
    assert meta["filename"].startswith("wa_backup_")

    eng2 = create_engine("sqlite:///" + str(db_file))
    s2 = sessionmaker(bind=eng2, autoflush=False, expire_on_commit=False)()
    s2.query(WaContact).first().nama = "Diubah"
    s2.commit()
    s2.close()
    eng2.dispose()

    backup_path = backup_dir() / meta["filename"]
    wa_backup.restore_from_file(backup_path.read_bytes())

    eng3 = create_engine("sqlite:///" + str(db_file))
    s3 = sessionmaker(bind=eng3, autoflush=False, expire_on_commit=False)()
    assert s3.query(WaContact).first().nama == "Budi"
    s3.close()
    eng3.dispose()


def test_validate_rejects_wrong_schema(monkeypatch, tmp_path):
    bad = tmp_path / "bad.db"
    eng = create_engine("sqlite:///" + str(bad))
    eng.connect().close()
    eng.dispose()
    import pytest
    with pytest.raises(wa_backup.WhatsAppBackupError):
        wa_backup.validate_backup_file(bad)
