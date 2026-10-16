# Laporan H8E — Implementasi Backup & Restore Database

## Status Akhir: **PASS** (implementasi) — regresi penuh ditunda ke H8G

Backup, validasi, dan restore diimplementasikan dan lolos pemeriksaan terarah
(7 test + import check). Sesuai strategi **Build First, Test Later**, regresi
lengkap ditunda ke H8G. Database operasional **tidak** digunakan atau dimodifikasi.

---

## 1. Endpoint yang Tersedia (semua `Depends(require_ui_access)`)

| Endpoint | Fungsi | Autentikasi |
|----------|--------|-------------|
| `POST /api/admin/backup` | membuat backup SQLite, mengembalikan metadata aman (`filename`, `size`, `created_at`) | Bearer `UI_ACCESS_TOKEN` |
| `POST /api/admin/restore` | menerima body file SQLite, memvalidasi, lalu mengganti DB aktif | Bearer `UI_ACCESS_TOKEN` |

- Token tidak via query param. Tidak ada endpoint download file arbitrer.
- Respons tidak menampilkan path absolut/rahasia.

## 2. Mekanisme Backup

- `services/backup.py::create_backup(db_url)` menggunakan **SQLite Online Backup API**
  (`src.backup(dst)`), aman terhadap koneksi/transaksi aktif dan mode WAL.
- Lokasi backup dari env `BACKUP_DIR` (default `data/backups`) — di luar path statis web.
- Nama file unik dengan timestamp (`backup_YYYYMMDD_HHMMSS_ffffff.db`); tidak menimpa.
- Tidak ada penghapusan backup lama otomatis.

## 3. Mekanisme Validasi & Restore

- `validate_backup_file(path)`: `PRAGMA integrity_check` + cek tabel wajib
  (`vehicles`, `service_records`, `service_jobs`, `service_parts`) + `alembic_version`.
- `restore_from_file(db_url, data)`:
  1. Tulis upload ke file temp + **validasi dulu** (tidak menyentuh DB aktif sebelum valid).
  2. Buat **backup pemulihan** dari DB aktif.
  3. Ganti file secara atomik (`os.replace`).
  4. Bila gagal → pulihkan dari backup pemulihan.
- Tidak ada migrasi otomatis terhadap file backup.
- Batas ukuran upload 50 MB (`DEFAULT_MAX_BACKUP_BYTES`).
- Path traversal dicegah: tidak memakai nama file dari pengguna sebagai path.

## 4. Strategi Pemulihan saat Restore Gagal

- Sebelum mengganti: recovery backup dibuat.
- Saat gagal ganti: `shutil.copy2` recovery backup ke target.
- Endpoint `restore` memanggil `db_engine.dispose()` dulu agar koneksi SQLAlchemy API ditutup.

## 5. File yang Dibuat/Diubah

| File | Perubahan |
|------|-----------|
| `services/backup.py` | **baru** — `BackupError`, `create_backup`, `validate_backup_file`, `restore_from_file` |
| `api/app.py` | + `POST /api/admin/backup`, `POST /api/admin/restore` + import |
| `.env.example` | + `BACKUP_DIR=data/backups` |
| `tests/test_backup_restore.py` | **baru** — 7 test terarah |

## 6. Pemeriksaan yang Dijalankan & Hasil

- Import/sintaks: `import api.app, services.backup` → OK (11 route).
- Test terarah (temp DB): **7 passed** — backup valid, validate valid/corrupt/inkompatibel,
  restore mengganti data, restore menolak file invalid tanpa mengubah DB, endpoint auth 401.
- **Regresi lengkap: BELUM dijalankan** (ditunda ke H8G).

## 7. Keterbatasan & Risiko

1. **Restore memerlukan mode pemeliharaan** — bila proses bot berjalan terpisah dan
   menahan file SQLite, `os.replace` bisa gagal (terutama Windows). Disarankan bot
   dihentikan dulu sebelum restore.
2. Lock hanya in-process (`threading.RLock`) — tidak melindungi lintas proses (bot vs API).
3. Upload memakai raw body (bukan multipart) untuk menghindari dependency baru
   (`python-multipart`); UI browser perlu mengirim file sebagai raw bytes.
4. Restore tidak menjalankan migrasi pada file backup; hanya cek keberadaan tabel.
5. Tidak ada penghapusan backup lama otomatis (sesuai ketentuan).

## 8. Database Operasional & Migrasi

- `data/workshop.db` **tidak digunakan sebagai DB test dan tidak dimodifikasi**
  (read-only: 1 kendaraan, 0 servis, `alembic=fa7fa27bbb86`). `data/backups` belum dibuat.
- Migrasi `c7c0a1b2c3d4` **tetap pending** (tidak diterapkan).
