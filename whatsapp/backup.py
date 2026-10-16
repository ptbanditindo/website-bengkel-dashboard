"""Backup + restore for the WhatsApp CS database.

Uses the SQLite Online Backup API (consistent snapshot), the same approach as
services/backup.py, but validates the WhatsApp schema instead of the main one.
Never touches data/workshop.db.
"""

import os
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from services.backup import backup_dir, sqlite_path
from services.exceptions import ServiceError
from whatsapp.db import get_whatsapp_db_url


class WhatsAppBackupError(ServiceError):
    pass


WA_REQUIRED_TABLES = {"wa_contacts", "wa_messages", "wa_candidates", "wa_arrival_plans", "wa_owner_questions", "wa_agent_settings"}

_lock = threading.RLock()


def create_backup() -> dict:
    source = sqlite_path(get_whatsapp_db_url())
    if not source:
        raise WhatsAppBackupError("Backup hanya didukung untuk database SQLite.")
    with _lock:
        directory = backup_dir()
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = "wa_backup_" + timestamp + ".db"
        dest = directory / filename
        src = sqlite3.connect(source)
        try:
            dst = sqlite3.connect(str(dest))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    return {"filename": filename, "size": dest.stat().st_size, "created_at": timestamp}


def validate_backup_file(path: Path) -> None:
    try:
        conn = sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise WhatsAppBackupError("File bukan database SQLite yang valid: " + str(e))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise WhatsAppBackupError("File backup rusak (integrity check gagal).")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = WA_REQUIRED_TABLES - tables
        if missing:
            raise WhatsAppBackupError("Skema tidak kompatibel: tabel hilang " + str(sorted(missing)))
    finally:
        conn.close()


def restore_from_file(data: bytes) -> dict:
    target = Path(sqlite_path(get_whatsapp_db_url()))
    with _lock:
        tmp_upload = target.with_name(target.name + ".wa_upload_tmp")
        tmp_upload.write_bytes(data)
        try:
            validate_backup_file(tmp_upload)
        except Exception:
            tmp_upload.unlink(missing_ok=True)
            raise
        recovery = create_backup()
        try:
            tmp_dest = target.with_name(target.name + ".wa_restore_tmp")
            shutil.copy2(tmp_upload, tmp_dest)
            os.replace(tmp_dest, target)
        except Exception:
            recovery_path = backup_dir() / recovery["filename"]
            if recovery_path.exists():
                try:
                    shutil.copy2(recovery_path, target)
                except Exception:
                    pass
            raise WhatsAppBackupError("Restore gagal; database WhatsApp dipulihkan dari backup pemulihan.")
        finally:
            tmp_upload.unlink(missing_ok=True)
    return recovery
