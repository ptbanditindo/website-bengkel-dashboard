# Full Code Audit & Hardening — AI Bengkel Telegram

## Ringkasan
- Audit menyeluruh: backend (FastAPI), frontend (static), bot Telegram, integrasi AI (DeepSeek/Gemini), database & migrasi.
- 2 bug diperbaiki + 2 regression test ditambahkan.
- 294 test PASS (pytest memakai SQLite in-memory terisolasi — tidak menyentuh DB operasional).
- Database operasional **tidak diubah** selama audit.

## Bug yang ditemukan & diperbaiki
1. **Penghapusan stok tanpa cek referensi** (`services/stock_service.py`, `api/app.py`)
   - Sebelumnya stok yang dipakai di riwayat servis bisa dihapus → `ServicePart.stock_item_id` menggantung → kalkulasi "Keuntungan Barang" kembali hilang (None).
   - Sekarang `delete_item` menolak dengan `ConflictError` (HTTP 409) bila masih direferensikan oleh part.
2. **`is_authorized` tidak memangkas whitespace** (`bot/auth.py`)
   - `AUTHORIZED_USER_ID="111, 222"` sebelumnya gagal mengenali id `222` karena spasi tidak dipangkas.

## Regression test ditambahkan
- `tests/test_read_api.py::test_delete_referenced_stock_conflict`
- `tests/test_auth.py::test_is_authorized_strips_whitespace`

## File yang diubah
- `services/stock_service.py`
- `api/app.py`
- `bot/auth.py`
- `tests/test_auth.py`
- `tests/test_read_api.py`

## Catatan / risiko (belum diubah, perlu keputusan bila ingin ditindaklanjuti)
- **Startup menjalankan migrasi otomatis** (`init_db()` → alembic `upgrade head`) saat bot & API start. Non-destruktif (hanya menerapkan migrasi tertunda, tidak reset/downgrade), tetapi mekanismenya perlu disadari saat deploy.
- **AI belum bisa menyatakan "tidak bergaransi"**: tool AI hanya punya `garansi_sampai` (tanggal). Ini gap fitur (bukan bug); UI sudah bisa menandai "tidak bergaransi".
- **`PicklePersistence`** untuk state Telegram memakai pickle — risiko eksekusi kode jika file diubah pihak tak berwenang (risiko rendah untuk bot admin lokal).
- **`parse_money` tidak mendukung nominal majemuk** seperti "2 juta 500 ribu" (ditolak sebagai tidak valid → aman).

## Hasil pengujian
- PASS: 294 test.
- NOT TESTED: live Telegram / DeepSeek / Gemini (dilarang oleh instruksi audit).
- BLOCKED: tidak ada.

## Status Git & data
- Database operasional: **tidak diubah**.
- Git: banyak file belum di-commit (proyek dibangun di atas repo lama; `ai/`, `api/`, `bot/`, `database/`, `migrations/`, `repositories/`, `services/`, `static/`, `tests/` untracked). DB operasional sudah di-gitignore (`data/*.db`).
