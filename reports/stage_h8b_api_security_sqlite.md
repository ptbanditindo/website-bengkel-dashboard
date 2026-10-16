# Laporan H8B — Pengamanan Backend & Fondasi Akses UI Lokal

## Status Akhir: **PASS**

Fondasi autentikasi API, pembatasan akses lokal, dan penanganan konkurensi SQLite
telah diimplementasikan dan diuji (208 test lulus). Database operasional tidak
disentuh; WAL tidak diterapkan ke `data/workshop.db` (sesuai instruksi).

---

## 1. Ringkasan Implementasi

| Area | Perubahan |
|------|-----------|
| Autentikasi API | Dependensi `require_ui_access` (Bearer token `UI_ACCESS_TOKEN`), constant-time compare, fail-closed |
| Endpoint | `/` terlindungi; `/health` publik (minimal) |
| Dokumentasi API | `/docs`, `/redoc`, `/openapi.json` **dinonaktifkan** |
| Akses jaringan | Default `APP_HOST=127.0.0.1` **tidak diubah** |
| SQLite | `PRAGMA busy_timeout=5000` pada semua koneksi baru; helper `enable_wal()` (tidak diterapkan ke operasional) |
| Konfigurasi | `.env.example` menambah placeholder `UI_ACCESS_TOKEN` |

## 2. File yang Diubah & Alasan

| File | Perubahan | Alasan |
|------|-----------|--------|
| `api/app.py` | `require_ui_access` + lindungi `/` + nonaktifkan docs | autentikasi API |
| `database/session.py` | `busy_timeout=5000` di listener koneksi + `enable_wal()` | konkurensi SQLite |
| `.env.example` | `UI_ACCESS_TOKEN=` placeholder | dokumentasi konfigurasi |
| `tests/test_api.py` | `test_root` → `test_root_requires_auth` (503) | root kini terlindungi |
| `tests/test_api_security.py` | **baru** (7 test auth) | verifikasi keamanan |
| `tests/test_database.py` | 2 test pragma SQLite | verifikasi busy_timeout/WAL |

## 3. Mekanisme Autentikasi

- Token dibaca dari environment `UI_ACCESS_TOKEN` (bukan hardcoded).
- Header: `Authorization: Bearer <token>` (bukan query parameter).
- Perbandingan dengan `secrets.compare_digest` (constant-time).
- **Fail closed:** token kosong → `503`; tanpa token/token salah → `401`.
- Token/header tidak pernah dicatat ke log.
- `/health` tetap publik (hanya `{"status": "ok"}`, tanpa rahasia/konfigurasi).

## 4. Kebijakan Host & Akses Jaringan

- `run_api.py` tetap memakai `APP_HOST` (default `127.0.0.1`), `APP_PORT` (default 8000).
- Tidak ada bind `0.0.0.0`, tidak ada pembukaan port, tidak ada perubahan Docker.
- `/docs`, `/redoc`, `/openapi.json` dinonaktifkan (tidak diandalkan sebagai pengganti auth).
- **Peringatan deployment:** mengubah `APP_HOST` ke `0.0.0.0` akan mengekspos API
  tanpa proteksi jaringan; wajib bind loopback + token, atau HTTPS + auth sebelum publik.

## 5. Konfigurasi SQLite

- `busy_timeout=5000` diterapkan lewat event `connect` SQLAlchemy → berlaku pada
  **setiap koneksi baru** (bukan hanya koneksi pertama), untuk proses bot maupun API.
- `enable_wal(engine)` tersedia dan **diuji pada database sementara**, tetapi **tidak
  diterapkan** ke `data/workshop.db` (journal mode operasional tetap `delete`).
- WAL bukan jaminan menghilangkan semua konflik tulis; busy_timeout mengurangi
  "database is locked" untuk konflik singkat. WAL untuk operasional butuh langkah terkontrol terpisah.

## 6. Pengujian Baru & Hasil Aktual

- `tests/test_api_security.py` (7): tanpa token 401, token salah 401, token valid 200,
  fail-closed 503, `/health` publik minimal, error tidak membocorkan token, docs 404.
- `tests/test_database.py` (+2): `busy_timeout=5000` + `foreign_keys=ON` pada koneksi baru; `enable_wal` menghasilkan `journal_mode=wal` pada DB sementara.
- `tests/test_api.py`: `test_root_requires_auth` (503).

## 7. Regresi

- `python -m pytest -q` → **208 passed, 0 failed, 0 skipped** (199 + 9 baru).

## 8. Database Operasional

- **Tidak digunakan sebagai database test** (semua test memakai SQLite in-memory/sementara).
- Read-only: 1 kendaraan, 0 riwayat servis, `alembic_version=fa7fa27bbb86`,
  `journal_mode=delete`. **Tidak dimodifikasi.**

## 9. Status Migrasi `c7c0a1b2c3d4`

- **Masih pending** (tidak diterapkan selama H8B). Tetap berlaku otomatis saat `init_db()` berikutnya.

## 10. Status Git (awal vs akhir)

- Awal H8B: banyak perubahan sudah ada (tracked `M`: `.env.example`, `.gitignore`, `Dockerfile`, `README.md`, `docker-compose.yml`, `main.py`, `requirements.txt`; untracked `??`: `ai/`, `api/`, `bot/`, `data/`, `database/`, `migrations/`, `reports/`, `repositories/`, `services/`, `tests/`, `run_api.py`, `alembic.ini`).
- Perubahan H8B terjadi **di dalam** file yang sudah modified/untracked tersebut (`.env.example`, `api/app.py`, `database/session.py`, `tests/*`). Tidak ada operasi Git destruktif.

## 11. Keterbatasan

1. WAL belum diterapkan ke database operasional (butuh langkah terkontrol + persetujuan).
2. Autentikasi memakai token statis (bukan sesi/OAuth); cukup untuk UI lokal, perlu evaluasi bila diekspos publik.
3. UI/frontend, endpoint CRUD, dan backup/restore belum dibuat (di luar cakupan H8B).

## 12. Rekomendasi Tahap Selanjutnya

1. Terapkan WAL operasional saat disetujui (satu kali `PRAGMA journal_mode=WAL`).
2. Tambahkan endpoint baca (dashboard/kendaraan/riwayat) dengan `get_db()` + `Depends(require_ui_access)`.
3. Bangun UI browser lokal (HTML/Jinja2 atau SPA) yang mengirim `Authorization: Bearer`.
