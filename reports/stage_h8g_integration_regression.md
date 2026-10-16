# Laporan H8G — Pengujian Integrasi & Regresi H8A–H8E

## Status Akhir: **PASS**

Regresi lengkap + pengujian integrasi gabungan lolos tanpa kegagalan.
Database operasional **tidak** digunakan sebagai DB uji dan **tidak** dimodifikasi.

---

## 1. Ringkasan Hasil Tes

| Metrik | Nilai |
|--------|-------|
| Total ditemukan | 241 |
| Lulus (passed) | **241** |
| Gagal (failed) | **0** |
| Dilewati (skipped) | **0** |

Perintah yang benar-benar dijalankan:

```
python -m pytest -q
```

Hasil: `241 passed, 3 warnings` (warnings: deprecation `httpx`/`starlette.testclient`
dan `PTBUserWarning` ConversationHandler — keduanya tidak memengaruhi hasil).

### Distribusi per tahap (dikonfirmasi via `--collect-only`)

| Tahap | File test | Jumlah |
|-------|-----------|--------|
| H8B keamanan API | `tests/test_api_security.py` (7) + `tests/test_database.py` (+2) | 9 |
| H8C API baca | `tests/test_read_api.py` | 16 |
| H8D API edit | `tests/test_vehicle_edit_api.py` | 9 |
| H8E backup/restore | `tests/test_backup_restore.py` | 7 |
| H8G integrasi gabungan | `tests/test_h8_integration.py` (**baru**) | 1 |
| Basis + tahap sebelumnya (H2–H8A) | seluruh file `tests/*.py` lainnya | 199 |

Total = 199 + 9 + 16 + 9 + 7 + 1 = **241**.

---

## 2. Hasil per Tahap H8A–H8E

### H8A — Kesiapan UI lokal
- FastAPI berjalan via `run_api.py` (loopback default), `main.py` bot terpisah.
- Tidak ada perubahan regresi; seluruh test basis lolos.

### H8B — Keamanan API & fondasi SQLite
- `GET /health` publik & minimal (`{"status": "ok"}`) — terverifikasi.
- Endpoint data tanpa token → 401; token salah → 401; token kosong terkonfigurasi → 503 (fail-closed); token valid → 200.
- Semua endpoint baca/edit/backup/restore memakai `Depends(require_ui_access)`.
- `/docs`, `/redoc`, `/openapi.json` → 404 (dinonaktifkan).
- `busy_timeout=5000` + `foreign_keys=ON` pada koneksi baru; `enable_wal` hanya pada DB sementara.

### H8C — API baca
- Dashboard: hitungan kendaraan/servis, 5 riwayat terbaru deterministik, kendaraan tidak lengkap.
- Pagination (`limit`/`offset`) dan pencarian plat ternormalisasi (`q=b 1111 aaa` → `B1111AAA`).
- Detail kendaraan + relasi riwayat servis benar; uang diserialisasi `str(Decimal)` tanpa kehilangan presisi; tanggal/waktu ISO konsisten; data tidak ada → 404.

### H8D — API edit
- Update parsial hanya mengubah field yang dikirim (khusus: `nama_client` yang tidak dikirim **tidak** berubah — terverifikasi `model_dump(exclude_unset=True)` + test).
- Normalisasi plat konsisten dengan pencarian; duplikat → 409 tanpa mengubah data; input invalid → 422; body kosong → 400; riwayat servis/jasa/part/harga/relasi tidak berubah; kendaraan lain tidak terpengaruh.

### H8E — Backup & restore
- Backup menghasilkan SQLite valid dan lolos `PRAGMA integrity_check`.
- Nama file unik (timestamp) → tidak menimpa.
- File rusak & skema tidak kompatibel ditolak (`BackupError`).
- Restore valid mengganti data; restore invalid tidak mengubah DB target.
- Mekanisme pemulihan: recovery backup dibuat sebelum ganti; pada kegagalan `os.replace`, DB aktif dipulihkan dari recovery backup.
- Autentikasi backup/restore diuji (401); batas ukuran 50 MB; input kosong → 400; file tak valid → 422.

---

## 3. Hasil Pengujian Integrasi Gabungan (E)

Test baru `tests/test_h8_integration.py::test_read_edit_backup_restore_chain`
menjalankan rangkaian penuh pada **database file sementara**:

1. Seed kendaraan + 1 riwayat servis → `GET /api/vehicles` (1 data).
2. Edit parsial (`nama_client`) via `PUT`.
3. Verifikasi detail + pencarian.
4. Verifikasi riwayat servis tetap utuh.
5. `POST /api/admin/backup`.
6. Ubah data uji.
7. `POST /api/admin/restore` (upload backup bytes).
8. Verifikasi hasil restore (kembali ke nilai pra-modifikasi).
9. Konfirmasi tidak ada data tercampur ke DB operasional.

Hasil: **lulus**. Tidak ada endpoint restore yang diarahkan ke DB operasional.

---

## 4. Masalah yang Ditemukan & Perbaikan

1. **(Temuan saat membangun test integrasi, bukan bug produksi)** Endpoint
   `POST /api/admin/restore` memanggil `db_engine.dispose()` sebelum mengganti file.
   Dalam produksi, `db_engine` dan `get_db` adalah engine yang sama, sehingga
   `dispose()` menutup koneksi SQLAlchemy ke DB yang akan diganti — benar.
   Dalam test, `get_db` di-override ke engine sementara sementara `db_engine`
   masih menunjuk engine operasional; ini membuat `os.replace` gagal (file masih
   terkunci). **Perbaikan:** test menambahkan `monkeypatch.setattr(api_app, "db_engine", eng)`
   agar `dispose()` menutup engine sementara yang benar. **Tidak ada perubahan kode produksi.**

2. Tidak ada kegagalan lain. Tidak ada test lama yang dimodifikasi untuk sekadar lulus,
   dan cakupan tidak dikurangi.

### Tes yang ditambahkan/diubah
- **Baru:** `tests/test_h8_integration.py` (1 test integrasi gabungan).
- **Diubah:** tidak ada (semua test lama tetap).


---

## 5. Pemeriksaan Kompatibilitas Migrasi (statis, tanpa menjalankan migrasi)

| Aspek | Status | Bukti |
|-------|--------|-------|
| Model `Vehicle.nama_client` | `nullable=True` | `database/models.py:50` |
| Migrasi `c7c0a1b2c3d4` | `upgrade()` → `nullable=True`, `existing_type=String(255)` | `migrations/versions/c7c0a1b2c3d4_*.py` |
| API `nama_client` opsional | `VehicleUpdate.nama_client: str \| None = None`; `VehicleSummary.nama_client: str \| None` | `api/schemas.py` |

- **Konsisten:** model ↔ migrasi ↔ API sepakat `nama_client` opsional (panjang 255).
- **Verifikasi via DB sementara:** test create/update dengan `nama_client` opsional lolos.
- **Hanya diperiksa statis (belum terverifikasi runtime):** kolom aktual DB operasional
  masih `NOT NULL` (migrasi pending), sehingga model (nullable) dan skema fisik (NOT NULL)
  belum sinkron sampai migrasi diterapkan.
- **Backup:** validasi backup berbasis keberadaan tabel (bukan nullability kolom) dan
  restore **tidak** menjalankan migrasi. Artinya file backup skema lama (dengan nilai
  `nama_client` terisi) tetap dapat dipulihkan ke aplikasi saat ini; namun backup yang
  mengandung `nama_client` NULL baru valid bila skema DB sudah nullable. Backup skema lama
  **tidak otomatis** kompatibel dengan semua versi aplikasi — kompatibilitas dibatasi
  pada kasus nilai kolom yang terisi.

---

## 6. Risiko yang Masih Tersisa

1. **Lintas proses (bot vs API):** `threading.RLock` di `services/backup.py` hanya
   melindungi dalam satu proses. Bila bot dan API berjalan sebagai proses terpisah,
   keduanya bisa menahan file SQLite; `os.replace` saat restore dapat gagal (terutama
   Windows). **Restore aman terhadap kegagalan internal (recovery backup) — namun tidak
   diklaim aman terhadap konflik lintas proses.** Disarankan mode pemeliharaan (bot
   dihentikan) saat restore.
2. **Upload raw body** (bukan multipart) — browser harus mengirim file sebagai raw bytes.
3. **Migrasi pending** `c7c0a1b2c3d4` — skema fisik DB operasional belum nullable.
4. **Warning dependensi** (`httpx` vs `httpx2`) tidak fungsional saat ini.

---

## 7. Status Migrasi

- `fa7fa27bbb86` (initial schema) adalah versi yang **terpasang** pada DB operasional.
- `c7c0a1b2c3d4_make_nama_client_optional` **tetap pending** — tidak dijalankan.
  Terverifikasi read-only: kolom `nama_client` masih `notnull=1`.

---

## 8. Konfirmasi Database Operasional

`data/workshop.db` **tidak** digunakan sebagai database uji dan **tidak** dimodifikasi.
Pemeriksaan read-only (`file:...?mode=ro`) setelah seluruh pengujian:

```
vehicles: 1, service_records: 0, service_jobs: 0, service_parts: 0
alembic: fa7fa27bbb86, nama_client notnull: 1
```

Tidak ada `init_db()`/migrasi/WAL terhadap DB operasional; `data/backups` tidak dibuat.

---

## 9. Rekomendasi

**Fondasi H8A–H8E layak dilanjutkan ke H8F (pembangunan UI browser).**

- Seluruh 241 test lolos; interaksi antartahap terverifikasi end-to-end pada DB sementara.
- Tidak ada kegagalan yang belum dijelaskan; tidak ada perubahan kode produksi di H8G.
- Sebelum H8F, disarankan mencatat dua prasyarat operasional: (a) terapkan migrasi
  `c7c0a1b2c3d4` bila `nama_client` opsional diperlukan, dan (b) hentikan bot saat restore.

