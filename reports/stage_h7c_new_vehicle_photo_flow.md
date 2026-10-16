# Laporan H7C — Alur Foto Nota, Pendaftaran Kendaraan Baru, dan Kesiapan UI Lokal

## Status Akhir: **PARTIAL PASS**

Seluruh kebutuhan utama dan regresi lulus secara deterministik (199 test). Yang
belum terverifikasi: OCR Gemini foto nyata (key kosong) dan live Telegram E2E.

---

## 1. File yang Diubah & Alasan

| File | Perubahan | Alasan |
|------|-----------|--------|
| `database/models.py` | `nama_client` → `nullable=True` | nama klien opsional untuk kendaraan dari foto |
| `migrations/versions/c7c0a1b2c3d4_make_nama_client_optional.py` | migrasi baru (batch_alter_table) | menyelaraskan skema operasional (pending, belum dijalankan) |
| `services/service_record_service.py` | `record_service_visit` pakai `clean_optional(nama_client)` | nama opsional |
| `ai/orchestrator.py` | `execute_pending` re-raise saat gagal (rollback dulu) | pesan konfirmasi sesuai hasil eksekusi |
| `ai/tools.py` | tambah `PhotoDraft` + `PhotoDraftStore` (user-bound, TTL, sekali pakai) | konteks foto menunggu plat |
| `bot/ai_runtime.py` | `self.photo_drafts = PhotoDraftStore()` | akses draf foto |
| `bot/ai_handlers.py` | tulis ulang handler foto (caption plat, tanya plat, kendaraan lama/baru) + `_process_photo_plate` + `_photo_confirm_summary` + routing draf di message handler | alur foto praktis |
| `tests/*` | perbarui 3 test foto + 1 orchestrator + 1 service; tambah 10 test baru | perilaku baru |

## 2. Perilaku Alur Foto

### Kendaraan terdaftar
Foto → ekstrak → normalisasi plat → `find_vehicle_by_plate` → pending action
`add_service_record` (kendaraan lama, tanpa duplikat, tanpa ubah data pelanggan).

### Kendaraan baru
Foto → plat → pending action `record_service_visit` (atomik: buat kendaraan +
riwayat servis dalam satu transaksi) dengan `nama_client=None`, `nomor_wa=None`,
jenis/tahun/alamat kosong. **Tidak meminta nama/WA/jenis/tahun/alamat.**

### Plat tidak disertakan
Handler menyimpan draf di `PhotoDraftStore` (terikat user, TTL 30 menit, sekali
pakai) dan meminta plat. Balasan teks pengguna diteruskan ke `_process_photo_plate`.

### Caption plat
`update.message.caption` diprioritaskan di atas plat hasil ekstraksi.

## 3. Nama & WhatsApp Opsional

- `Vehicle.nama_client` kini nullable; `record_service_visit` memakai `clean_optional`.
- Alur manual `/daftar` tetap mensyaratkan nama (`create_vehicle` tetap `clean_required`).
- Alur chat DeepSeek tetap mensyaratkan nama untuk kendaraan baru (cek di `_plan_record_service_visit`).

## 4. Pesan Konfirmasi Sesuai Hasil Eksekusi

- `execute_pending` kini **melempar ulang** `ServiceError`/exception setelah rollback.
- Handler `ai_confirm_callback` (sudah ada try/except) kini menampilkan:
  - sukses → `✅ Berhasil` (hanya setelah commit),
  - validasi gagal → `❌ {pesan}`,
  - error DB → `❌ Terjadi kesalahan. Data tidak tersimpan.`,
  - token invalid/kedaluwarsa/milik lain → `❌ Konfirmasi tidak valid...`.
- Dibuktikan oleh `test_ai_confirm_failure_shows_error_not_success` dan
  `test_ai_confirm_success_shows_success`.

## 5. Atomisitas, Rollback, Pencegahan Duplikasi

- `record_service_visit` satu transaksi (commit/rollback bersama).
- `execute_pending` rollback seluruh aksi saat gagal (test rollback).
- Konflik plat (didaftarkan pengguna lain sebelum konfirmasi) → `record_service_visit`
  memakai kendaraan lama, tidak duplikat (`test_ai_photo_new_vehicle_confirm_race_no_duplicate`).
- Konfirmasi berulang → token sekali pakai (`test_ai_confirm_rejects_reused_token`).

## 6. Kesiapan UI Lokal

- `update_vehicle` sudah mendukung edit nama/WA/jenis/tahun/alamat tanpa menghapus
  riwayat (`test_update_vehicle_keeps_service_records`).
- Pencarian plat (`find_vehicle_by_plate`), riwayat servis (`list_service_records`),
  dan relasi kendaraan↔servis sudah ada. **Tidak perlu tabel/migrasi baru untuk UI lokal.**

## 7. Pengujian

- `python -m pytest -q` → **199 passed, 0 failed, 0 skipped**.
- 10 test baru: 7 handler (kendaraan baru, lanjut plat, caption, plat kosong, race,
  pesan gagal/sukses), 2 `PhotoDraftStore`, 1 service (update tanpa hapus riwayat).
- 5 test lama diperbarui untuk perilaku H7C (bukan dilemahkan).

## 8. Database Operasional

- `data/workshop.db` **tidak berubah** (read-only: 1 kendaraan, 0 servis).
- Versi Alembic tetap `fa7fa27bbb86`; migrasi `c7c0a1b2c3d4` **pending** (diterapkan
  pada `init_db()` berikutnya, non-destruktif).

## 9. API Live & Telegram Live

- **Tidak ada** pemanggilan DeepSeek/Gemini live, polling Telegram, atau webhook.
- Seluruh pengujian memakai mock provider + SQLite sementara.

## 10. Keterbatasan

1. OCR Gemini pada foto nyata **belum diuji** (key kosong).
2. Live Telegram E2E belum diuji.
3. Migrasi `c7c0a1b2c3d4` belum diterapkan ke DB operasional (pending).

## 11. Kesimpulan

Alur foto untuk kendaraan terdaftar dan baru, nama/WA opsional, pesan konfirmasi
akurat, atomisitas, dan kesiapan UI lokal — semuanya terverifikasi deterministik.
Status **PARTIAL PASS** karena OCR Gemini live dan Telegram E2E belum diverifikasi.
