# Laporan H8C — Implementasi API Baca untuk UI Lokal

## Status Akhir: **PASS**

Endpoint baca (dashboard, kendaraan, pencarian, detail, riwayat servis) telah
diimplementasikan, semua terlindungi autentikasi, dan diuji deterministik (224 test
lulus). Database operasional tidak disentuh; tidak ada migrasi yang dijalankan.

---

## 1. Endpoint yang Dibuat (semua `Depends(require_ui_access)`)

| Endpoint | Respons |
|----------|---------|
| `GET /api/dashboard` | `vehicle_count`, `service_record_count`, `recent_service_records[5]`, `incomplete_vehicles_count` |
| `GET /api/vehicles?limit&offset` | daftar kendaraan (pagination) |
| `GET /api/vehicles/search?q=` | pencarian (plat dinormalisasi) |
| `GET /api/vehicles/{id}` | detail + `missing_fields` + `service_record_count` |
| `GET /api/vehicles/{id}/service-records` | riwayat servis kendaraan |
| `GET /api/service-records/{id}` | detail riwayat servis (jasa/part/harga/total) |

## 2. Bentuk Respons

- Uang (`Decimal`) diserialisasi sebagai **string** (`"50000.00"`) untuk menjaga presisi.
- Tanggal/waktu diserialisasi ISO (Pydantic).
- Skema Pydantic eksplisit di `api/schemas.py`.
- `incomplete_vehicles_count` = kendaraan yang salah satu dari (nama, WA, jenis, tahun, alamat) bernilai `None`.
- `recent_service_records` lintas semua kendaraan, urut `waktu_service DESC, id DESC` (deterministik), batas 5.
- Kendaraan/riwayat tidak ditemukan → HTTP `404`.

## 3. File yang Diubah & Alasan

| File | Perubahan | Alasan |
|------|-----------|--------|
| `api/schemas.py` | **baru** — skema Pydantic respons | skema eksplisit, tanpa SQLAlchemy mentah |
| `api/app.py` | endpoint baca + helper serialisasi | API baca |
| `services/reporting.py` | `recent_service_records` + `incomplete_vehicles_count` | query dashboard |
| `repositories/vehicle_repository.py` | `list_all(limit, offset)` + pencarian plat dinormalisasi | pagination + normalisasi |
| `services/vehicle_service.py` | `list_vehicles(limit, offset)` | pagination |
| `tests/test_read_api.py` | **baru** — 16 test | verifikasi endpoint |

## 4. Service/Repository yang Digunakan Kembali

- `VehicleService.get_vehicle`, `list_vehicles`, `search_vehicles_filtered`.
- `ServiceRecordService.get_service_record`, `list_service_records`.
- `ReportingService.count_vehicles`, `count_service_records`, `recent_service_records`, `incomplete_vehicles_count`.
- Endpoint **tidak** mengakses database langsung (selalu lewat service).

## 5. Autentikasi

- Seluruh endpoint data memakai `Depends(require_ui_access)` (Bearer `UI_ACCESS_TOKEN`, constant-time, fail-closed) dari H8B.
- `/health` tetap publik (minimal). Token tidak lewat query parameter.

## 6. Pengujian Baru & Hasil

`tests/test_read_api.py` (16 test): hitungan dashboard, dashboard kosong, daftar,
pagination, limit invalid, pencarian plat dinormalisasi, detail ditemukan/tidak
lengkap/tidak ditemukan, riwayat per kendaraan, detail total-only (Decimal→string),
404 kendaraan/riwayat, riwayat tidak tercampur antar kendaraan, semua endpoint
terlindungi, endpoint baca tidak mengubah data.

## 7. Regresi

- `python -m pytest -q` → **224 passed, 0 failed, 0 skipped** (208 + 16 baru).

## 8. Database Operasional

- **Tidak digunakan sebagai database test** (semua test memakai engine in-memory via `dependency_overrides[get_db]`).
- Read-only: 1 kendaraan, 0 riwayat servis, `alembic_version=fa7fa27bbb86`. Tidak berubah.

## 9. Status Migrasi

- `c7c0a1b2c3d4_make_nama_client_optional` **tetap pending** (tidak diterapkan).
- `nama_client` opsional di model source code, sedangkan skema operasional masih `NOT NULL` — dicatat sebagai prasyarat yang akan selesai saat `init_db()` berikutnya.

## 10. Status Git

- Perubahan H8C terjadi di dalam file yang sudah modified/untracked (`.env.example` tidak diubah pada H8C; `api/app.py`, `api/schemas.py`, `services/reporting.py`, `repositories/vehicle_repository.py`, `services/vehicle_service.py`, `tests/test_read_api.py`).
- Tidak ada operasi Git destruktif.

## 11. Keterbatasan & Prasyarat Tahap Selanjutnya

1. `nama_client` masih `NOT NULL` di DB operasional (migrasi pending); API sudah siap untuk nilai null.
2. Belum ada endpoint edit/CRUD dan backup/restore (di luar cakupan H8C).
3. UI/frontend belum dibuat.
4. Pagination `limit/offset` dibatasi maks 200 per request.

## 12. Rekomendasi Tahap Selanjutnya

1. Terapkan migrasi `c7c0a1b2c3d4` saat disetujui (agar `nama_client` null di DB operasional).
2. Tambah endpoint edit (`update_vehicle`) dan backup/restore.
3. Bangun UI browser lokal yang memanggil endpoint ini dengan `Authorization: Bearer`.
