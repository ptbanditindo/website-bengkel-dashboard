# Laporan H6B — Audit & Pengujian Telegram End-to-End

## Status Akhir: **PARTIAL PASS**

Integrasi deterministik jalur Telegram lulus (mock update/context + provider +
SQLite sementara). **Live Telegram end-to-end belum diuji** (membutuhkan akun uji
& polling nyata yang tidak aman dilakukan tanpa izin), sehingga tidak diklaim PASS penuh.

---

## BAGIAN A — Audit Jalur Telegram (kode nyata)

| Komponen | Temuan |
|----------|--------|
| Inisialisasi bot | `build_application()` memanggil `init_db()` (non-destructive), PicklePersistence, registrasi command/conversation/callback/AI handler |
| Otorisasi | **Semua** handler AI (`ai_message_handler`, `ai_confirm_callback`, `ai_cancel_callback`, `ai_photo_handler`) ber-`@require_auth`; handler manual juga |
| Mutasi tanpa konfirmasi | **Tidak ada.** Mutasi hanya lewat `execute_pending` (setelah pending action + konfirmasi), atau callback manual (register/service) yang punya konfirmasi sendiri |
| Confirm/cancel | Token diikat ke `update.effective_user.id` (`PendingStore.get/pop` memeriksa user_id) |
| Error provider/DB | Provider error → balasan `❌` (tanpa mutasi); error DB di confirm → `❌` + rollback (di `execute_pending`) |
| Format respons | Ringkasan pending + tombol `✅ Konfirmasi` / `❌ Batal` |

**Temuan kecil (tidak diperbaiki — bukan bug fungsional):** `ai_cancel_callback`
selalu membalas "Dibatalkan" walau token tidak valid/milik pengguna lain (`pop`
mengembalikan `None` secara diam). Tidak ada dampak keamanan (token pengguna lain
tidak terhapus); dicatat sebagai catatan UX.

## BAGIAN B — Pengujian Integrasi Deterministik (mock update/context)

Ditambahkan 11 test handler-level di `tests/test_ai_handlers.py` (menggunakan jalur
handler sesungguhnya, bukan hanya service). Total test handler = 20.

| # | Butir wajib | Test |
|---|-------------|------|
| 1 | Pengguna berwenang → respons | `test_ai_message_handler_text_response` |
| 2 | Tidak berwenang → ditolak | `test_ai_message_handler_denies_unauthorized` |
| 3 | Instruksi → pending action valid | `test_ai_confirm_record_service_visit_*` (+ existing `shows_pending_buttons`) |
| 4 | Tidak ada data sebelum konfirmasi | `test_ai_confirm_record_service_visit_*` (count 0 sebelum confirm) |
| 5 | Konfirmasi → 1 kendaraan + 1 servis | `test_ai_confirm_record_service_visit_creates_vehicle_and_record` |
| 6 | Pembatalan → tanpa mutasi | `test_ai_cancel_no_db_change` |
| 7 | Token terpakai → ditolak | `test_ai_confirm_rejects_reused_token` |
| 8 | Token pengguna lain → ditolak | `test_ai_confirm_rejects_other_user` |
| 9 | Pencarian benar | `test_ai_message_handler_search_read_no_pending` (+ tool-level `test_ai_tools.py`) |
| 10 | Tool laporan cocok fixture | `test_ai_message_handler_report_no_pending` (+ `test_report_tools.py`) |
| 11 | Pesan tak lengkap → klarifikasi | `test_ai_message_handler_clarification_no_pending` |
| 12 | Error provider → tanpa mutasi parsial | `test_ai_message_handler_provider_error_no_mutation` |
| 13 | Callback invalid → ditolak aman | `test_ai_confirm_rejects_invalid_token` |

## BAGIAN C — Live Telegram

- **Tidak dijalankan.** Membutuhkan akun pemilik uji, polling nyata, dan isolasi
  database bot nyata yang tidak dapat dijamin aman tanpa izin. Sesuai aturan,
  diuji dengan mock dan **live E2E ditandai belum diuji**.

## BAGIAN D — Regresi

- `python -m pytest -q` → **166 passed, 0 failed, 0 skipped** (155 + 11 baru).

## BAGIAN E — Keamanan & Database

- Otorisasi, konfirmasi eksplisit, atomisitas, isolasi pending action, token
  sekali pakai & kedaluwarsa — semuanya terverifikasi.
- `data/workshop.db` **tidak berubah** (read-only: 1 kendaraan, 0 servis).
- Tidak ada token/API key tercetak.

## Keterbatasan & Rekomendasi

1. **Live Telegram E2E belum diuji** (butuh akun uji + izin).
2. `ai_cancel_callback` tidak memvalidasi token (catatan UX minor).
3. Alur foto (Gemini) tetap bergantung `add_service_record` untuk kendaraan yang
   sudah ada — di luar cakupan (Gemini belum dikonfigurasi).

**Rekomendasi:** uji live Telegram satu sesi terkendali dengan akun pemilik saat
tersedia, dengan database uji terisolasi.
