"""SQLite backup, validation, and restore (H8E).

Uses the SQLite Online Backup API for consistent backups. Restore validates the
uploaded file (integrity + schema) before touching the active database, creates a
recovery backup, and replaces the file atomically. Never used against
``data/workshop.db`` during development.
"""

import os
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from services.exceptions import ServiceError


class BackupError(ServiceError):
    """Raised when backup/restore fails or the uploaded file is invalid."""


DEFAULT_BACKUP_DIR = "data/backups"
DEFAULT_MAX_BACKUP_BYTES = 50 * 1024 * 1024  # 50 MB
REQUIRED_TABLES = {"vehicles", "service_records", "service_jobs", "service_parts"}

# In-process guard so backup/restore never run concurrently within one process.
# Reentrant: restore_from_file holds it while calling create_backup (recovery).
_lock = threading.RLock()


def backup_dir() -> Path:
    return Path(os.getenv("BACKUP_DIR", DEFAULT_BACKUP_DIR))


def sqlite_path(db_url: str) -> str | None:
    prefix = "sqlite:///"
    if db_url.startswith(prefix):
        return db_url[len(prefix):]
    return None


def create_backup(db_url: str) -> dict:
    """Create a consistent SQLite backup; return safe metadata."""
    source = sqlite_path(db_url)
    if not source:
        raise BackupError("Backup hanya didukung untuk database SQLite.")

    with _lock:
        directory = backup_dir()
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filename = f"backup_{timestamp}.db"
        dest = directory / filename

        src = sqlite3.connect(source)
        try:
            dst = sqlite3.connect(str(dest))
            try:
                src.backup(dst)  # SQLite Online Backup API (safe on active connections)
            finally:
                dst.close()
        finally:
            src.close()

    return {"filename": filename, "size": dest.stat().st_size, "created_at": timestamp}


def validate_backup_file(path: Path) -> None:
    """Raise BackupError if the file is not a compatible SQLite database."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise BackupError(f"File bukan database SQLite yang valid: {e}.")

    try:
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        except sqlite3.Error as e:
            raise BackupError(f"File backup rusak: {e}.")
        if integrity != "ok":
            raise BackupError("File backup rusak (integrity check gagal).")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            raise BackupError(f"Skema tidak kompatibel: tabel hilang {sorted(missing)}.")
        if "alembic_version" not in tables:
            raise BackupError("Skema tidak kompatibel: tabel alembic_version hilang.")
    finally:
        conn.close()


def restore_from_file(db_url: str, data: bytes) -> dict:
    """Validate and restore ``data`` into the active SQLite database.

    Creates a recovery backup first; on failure it rolls back to that backup.
    The caller is responsible for disposing open SQLAlchemy connections first.
    """
    path = sqlite_path(db_url)
    if not path:
        raise BackupError("Restore hanya didukung untuk database SQLite.")
    target = Path(path)

    with _lock:
        # Write upload to a temp file (same dir) and validate before touching the DB.
        tmp_upload = target.with_name(target.name + ".upload_tmp")
        tmp_upload.write_bytes(data)
        try:
            validate_backup_file(tmp_upload)
        except Exception:
            tmp_upload.unlink(missing_ok=True)
            raise

        recovery = create_backup(db_url)
        try:
            tmp_dest = target.with_name(target.name + ".restore_tmp")
            shutil.copy2(tmp_upload, tmp_dest)
            os.replace(tmp_dest, target)
        except Exception:
            recovery_path = backup_dir() / recovery["filename"]
            if recovery_path.exists():
                try:
                    shutil.copy2(recovery_path, target)
                except Exception:
                    pass
            raise BackupError("Restore gagal; database aktif dipulihkan dari backup pemulihan.")
        finally:
            tmp_upload.unlink(missing_ok=True)

    return recovery
