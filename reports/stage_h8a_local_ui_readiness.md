# Laporan H8A — Audit Kesiapan UI Lokal

## Status Akhir: **PARTIAL PASS**

Audit selesai tanpa mengubah source code, migrasi, konfigurasi, atau database.
Kesiapan fondasi UI lokal bersifat **sebagian**: mayoritas data/service siap,
tetapi autentikasi API, backup/pemulihan, dan penanganan konkurensi SQLite belum ada.

---

## 1. Ringkasan Arsitektur Aktual

| Aspek | Temuan | Bukti |
|-------|--------|-------|
| Entry point bot | `main.py` → `bot.application.run()` (polling) | `main.py`, `bot/application.py` |
| Framework Telegram | `python-telegram-bot` v20 | `requirements.txt` |
| Backend HTTP/API | **FastAPI** (minimal: hanya `/` dan `/health`) | `api/app.py`, `run_api.py` |
| UI web / template / static | **Tidak ada** (belum ada HTML/template/static/frontend) | pengecekan direktori |
| Konfigurasi | `.env` (dotenv), `APP_HOST=127.0.0.1` default | `.env.example`, `run_api.py` |
| Dependency UI | FastAPI + uvicorn sudah ada; **belum ada** framework template/HTML | `requirements.txt` |
| Docker | `Dockerfile` (bot saja), `docker-compose.yml` (volume `bot-data`) | `Dockerfile`, `docker-compose.yml` |

**Kesimpulan arsitektur:** fondasi backend (FastAPI) sudah tersedia, tetapi belum
ada frontend dan belum ada endpoint data (hanya health check, tanpa autentikasi).

## 2. Daftar File & Fungsi yang Diperiksa

- `api/app.py` — `app`, `lifespan` (memanggil `init_db`), `GET /`, `GET /health`.
- `run_api.py` — `main()` (uvicorn, host `APP_HOST`/port `APP_PORT`).
- `database/session.py` — `get_database_url`, `_build_engine`, `engine`, `SessionLocal`, `get_db`, `run_migrations`, `init_db`.
- `database/models.py` — `Vehicle`, `ServiceRecord`, `ServiceJob`, `ServicePart`, `normalize_plate`, `utcnow`.
- `migrations/versions/fa7fa27bbb86_initial_schema.py`, `migrations/versions/c7c0a1b2c3d4_make_nama_client_optional.py`, `migrations/env.py`.
- `repositories/vehicle_repository.py` — `get`, `find_by_plate`, `list_all`, `search`, `search_filtered`, `add`, `delete`.
- `repositories/service_record_repository.py` — `get`, `list_by_vehicle`, `add`.
- `services/vehicle_service.py` — `create_vehicle`, `find_vehicle_by_plate`, `get_vehicle`, `list_vehicles`, `search_vehicles`, `search_vehicles_filtered`, `update_vehicle`, `delete_vehicle`.
- `services/service_record_service.py` — `add_service_record`, `record_service_visit`, `get_service_record`, `list_service_records`, `get_vehicle_service_history`, `update_warranty`, `mark_claim`.
- `services/reporting.py` — `count_vehicles`, `count_service_records`, `service_totals`, `period_summary`, `top_jobs`, `part_usage`, `vehicles_under_warranty`, `activity_summary`, `search_records_by_job`.
- `bot/auth.py` — `is_authorized`, `require_auth`.

## 3. Audit Database & Migrasi

### 3.1 Kondisi skema/model di source code
- `Vehicle.nama_client` = `nullable=True` (opsional), `nopol` unique, relasi `service_records` (1-N), `ServiceRecord.jobs`/`parts` (1-N). `total_*`/`biaya_jasa`/`harga` = `Numeric(14,2)` (Decimal).

### 3.2 Versi migrasi yang tercatat
- `alembic_version` = **`fa7fa27bbb86`** (dibaca read-only dari `data/workshop.db`).

### 3.3 Migrasi yang masih pending
- **`c7c0a1b2c3d4_make_nama_client_optional.py`** (belum diterapkan).
- Isi: `batch_alter_table('vehicles')` → `alter_column('nama_client', nullable=True)`.
- **Audit dampak:** non-destruktif (hanya menghapus constraint NOT NULL; data tidak diubah). Diterapkan otomatis oleh `init_db()` pada start berikutnya. Tidak dijalankan selama audit.

### 3.4 Kondisi database operasional (verifikasi read-only)
- `data/workshop.db`: 1 kendaraan, 0 riwayat servis, alembic `fa7fa27bbb86`.

### 3.5 Berbagi database bot ↔ UI
- Engine dibuat dengan `check_same_thread=False` (SQLite). Bot dan UI dapat memakai engine/session yang sama via `get_db()`.
- **Risiko konkurensi:** SQLite tanpa WAL/busy_timeout → kemungkinan "database is locked" bila bot (AI/Telegram) dan UI menulis bersamaan. Ini **prasyarat yang harus ditangani** sebelum UI operasional.

## 4. Matriks Kesiapan Halaman UI

| Halaman / Fitur | Kesiapan | Fondasi (bukti) |
|-----------------|----------|-----------------|
| Dashboard — jumlah kendaraan | SIAP | `ReportingService.count_vehicles` |
| Dashboard — jumlah riwayat servis | SIAP | `ReportingService.count_service_records` |
| Dashboard — aktivitas servis terbaru | SEBAGIAN | tidak ada query "N riwayat terbaru lintas kendaraan" (hanya `list_by_vehicle`) |
| Dashboard — kendaraan data belum lengkap | SEBAGIAN | `nama_client`/`nomor_wa` nullable, tetapi belum ada query filter NULL |
| Kendaraan — daftar | SIAP | `VehicleService.list_vehicles` |
| Kendaraan — pencarian & normalisasi plat | SIAP | `search_vehicles_filtered` + `normalize_plate` |
| Kendaraan — detail | SIAP | `find_vehicle_by_plate` / `get_vehicle` |
| Kendaraan — status kelengkapan | SIAP | field nullable (`nama_client`, `nomor_wa`, `jenis_mobil`, `tahun_mobil`, `alamat_client`) |
| Detail/Edit — nama, WA, plat, jenis, tahun, alamat | SIAP | `VehicleService.update_vehicle` |
| Detail/Edit — validasi & plat duplikat | SIAP | `clean_*`, `validate_tahun`, `normalize_required_plate`, `ConflictError` |
| Riwayat servis — tanggal/jasa/part/harga/total | SIAP | model + `bot/formatting.format_service_record` |
| Riwayat servis — hubungan ke kendaraan | SIAP | `ServiceRecord.vehicle_id` FK |
| Backup & pemulihan | **BELUM SIAP** | tidak ada utilitas backup/restore/validasi file |
| Autentikasi API | **BELUM SIAP** | `api/app.py` tanpa auth; hanya health check |

## 5. Risiko & Prasyarat yang Ditemukan

1. **Konkurensi SQLite** (bot + UI menulis) — belum ada WAL/busy_timeout.
2. **Tanpa autentikasi API** — saat endpoint data ditambahkan, proses lokal mana pun bisa mengakses/mutasi.
3. **`APP_HOST=0.0.0.0`** (jika diubah) → eksposur publik tanpa auth.
4. **Kebocoran data pelanggan** — data di SQLite; API harus local-only + terautentikasi.
5. **VPS vs lokal** — SQLite adalah file lokal di host proses; UI di komputer lain tidak otomatis berbagi file (butuh SSH tunnel/VPN atau migrasi ke PostgreSQL bersama).
6. **Migrasi pending** `c7c0a1b2c3d4` — aman (non-destruktif) tetapi harus disadari saat start.

## 6. Rekomendasi Arsitektur UI

- **Backend:** FastAPI yang sudah ada; tambahkan endpoint read/edit yang memakai `get_db()` + service yang sama dengan bot (bukan akses SQL langsung).
- **UI:** halaman browser lokal (HTML + Jinja2/HTMX atau SPA statis) yang memanggil API.
- **Satu database** (`data/workshop.db`), tidak ada database kedua.
- **Akses aman:** bind `127.0.0.1` + token sederhana; tidak mengekspos `0.0.0.0`.
- **Tanpa AI API** untuk dashboard/view/edit data dasar.
- **VPS vs lokal:** jika bot di VPS (Docker), jalankan API di host yang sama dengan database, akses via SSH tunnel/VPN/HTTPS berautentikasi; alternatifnya pindah ke PostgreSQL bersama via `DATABASE_URL`.

## 7. Rencana Tahap Implementasi Berikutnya

1. Autentikasi API + bind loopback (keamanan).
2. Endpoint baca: dashboard, daftar/pencarian/detail kendaraan, riwayat servis.
3. Endpoint edit: `update_vehicle`.
4. Endpoint backup/pemulihan (sqlite3 backup API + validasi + rollback).
5. SQLite WAL + busy_timeout untuk konkurensi.
6. UI HTML minimal.
7. Test UI (temp DB) + regresi.

## 8. Pengujian yang Dijalankan & Hasil

- `python -m pytest -q` → **199 passed, 0 failed, 0 skipped** (read-only terhadap database operasional; seluruh test memakai SQLite in-memory/sementara).

## 9. File yang Berubah Selama Audit

- **Tidak ada.** H8A hanya membaca. Laporan `stage_h8a_local_ui_readiness.md` / `.json` adalah satu-satunya perubahan yang diizinkan.

## 10. Git Status (dicatat, tidak diubah)

- Banyak perubahan belum di-commit (tracked `M`: `.env.example`, `.gitignore`, `Dockerfile`, `README.md`, `docker-compose.yml`, `main.py`, `requirements.txt`; untracked `??`: `ai/`, `api/`, `bot/`, `data/`, `database/`, `migrations/`, `reports/`, `repositories/`, `services/`, `tests/`, `run_api.py`, `alembic.ini`).
- Tidak ada perubahan git yang dilakukan selama H8A.

## 11. Hal yang Belum Dapat Diverifikasi

1. Kemampuan OCR Gemini pada foto nyata (belum diuji, key kosong).
2. Live Telegram E2E (belum diuji).
3. Perilaku konkurensi SQLite nyata antara bot dan UI (belum ada UI untuk diuji).
4. Isi data pelanggan operasional tidak dibaca/ditampilkan (hanya jumlah record yang diverifikasi).

