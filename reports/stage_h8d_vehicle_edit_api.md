# Laporan H8D — Implementasi API Edit Data Kendaraan

## Status Akhir: **PASS** (implementasi) — regresi penuh ditunda ke H8G

Endpoint edit kendaraan diimplementasikan dan lolos pemeriksaan terarah (9 test +
import check). Sesuai strategi **Build First, Test Later**, pengujian regresi
lengkap dan integrasi gabungan **ditunda ke H8G** (tidak dijalankan pada tahap ini).

---

## 1. Endpoint & Format

`PUT /api/vehicles/{vehicle_id}`

- **Request** (`VehicleUpdate`, Pydantic) — pembaruan **parsial** (hanya field yang dikirim yang berubah):
  - `nama_client` (str, opsional)
  - `nomor_wa` (str, opsional)
  - `nopol` (str, opsional — dinormalisasi)
  - `jenis_mobil` (str, opsional)
  - `tahun_mobil` (int, opsional)
  - `alamat_client` (str, opsional)
- **Response** (`VehicleDetail`): ringkasan kendaraan + `missing_fields` + `service_record_count`.

## 2. Validasi & Penanganan Error

| Kondisi | Kode HTTP |
|---------|-----------|
| Kendaraan tidak ditemukan | `404` |
| Plat bertabrakan dengan kendaraan lain | `409` |
| Validasi gagal (tahun tidak valid, plat kosong, dll.) | `422` |
| Body kosong (tidak ada field) | `400` |
| Tanpa/ token salah | `401` / `503` (H8B) |

- Plat dinormalisasi via `update_vehicle` (aturan normalisasi proyek).
- Tidak ada data diubah saat validasi gagal (commit hanya setelah validasi).
- Tidak ada pembuatan kendaraan baru lewat endpoint edit.

## 3. Perlindungan Riwayat Servis

- Endpoint memakai `VehicleService.update_vehicle` (hanya mengubah field `Vehicle`).
- **Tidak** menyentuh `ServiceRecord`/`ServiceJob`/`ServicePart`.
- Dibuktikan test `test_edit_preserves_service_records`: setelah edit, riwayat tetap 1,
  `vehicle_id` sama, jasa "Ganti oli" tidak berubah.

## 4. Autentikasi

- `Depends(require_ui_access)` (Bearer `UI_ACCESS_TOKEN`, H8B). Token tidak via query param.
- `/health` tetap publik minimal. Host default tetap loopback.

## 5. File yang Diubah

| File | Perubahan |
|------|-----------|
| `api/schemas.py` | + `VehicleUpdate` (request schema) |
| `api/app.py` | + endpoint `PUT /api/vehicles/{vehicle_id}` + import `ConflictError`/`ValidationError` |
| `tests/test_vehicle_edit_api.py` | **baru** — 9 test terarah |

## 6. Pemeriksaan yang Dijalankan & Hasil

- Import/sintaks: `import api.app, api.schemas` → OK (9 route terdaftar).
- Test terarah (in-memory DB via `dependency_overrides[get_db]`): **9 passed**.
  - edit nama, edit WA, edit plat (normalisasi), plat duplikat 409, tidak ditemukan 404,
    tanpa token 401, riwayat servis terjaga, tahun invalid 422, body kosong 400.
- **Regresi lengkap: BELUM dijalankan** (ditunda ke H8G). Tidak diklaim semua tes lulus.

## 7. Database Operasional

- **Tidak digunakan/diubah.** Read-only: 1 kendaraan, 0 riwayat servis, `alembic=fa7fa27bbb86`.
- Migrasi `c7c0a1b2c3d4` **tetap pending** (tidak diterapkan).

## 8. Kendala / Prasyarat

1. `VehicleService.update_vehicle` masih memakai `clean_required` untuk `nama_client`,
   sehingga nama **tidak dapat dikosongkan** lewat endpoint ini (hanya diisi/ubah non-kosong).
   Ini konsisten dengan laporan H8A (edit nama = SIAP), tetapi membatasi penghapusan nama.
2. Regresi penuh & integrasi gabungan menunggu H8G.
