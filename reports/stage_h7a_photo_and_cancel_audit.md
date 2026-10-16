# Laporan H7A — Audit Handler Foto & Perbaikan UX Pembatalan

## Status Akhir: **PASS**

UX pembatalan diperbaiki (terbukti bug), alur foto diaudit menyeluruh (tidak ada
bug terbukti — hanya catatan desain), 14 test baru ditambahkan, dan seluruh regresi
(180 test) lulus.

---

## BAGIAN A — Perbaikan UX Pembatalan

**Bug terbukti:** `ai_cancel_callback` selalu membalas "Dibatalkan" meskipun
`PendingStore.pop(token, user_id)` mengembalikan `None` (token invalid/kedaluwarsa/
sudah dipakai/milik pengguna lain).

**Perbaikan (`bot/ai_handlers.py`):** periksa hasil `pop`:
- `removed is not None` → "❌ Dibatalkan. Tidak ada data yang disimpan."
- selain itu → "❌ Konfirmasi tidak valid, kedaluwarsa, atau bukan milik Anda."

**Tidak dilemahkan:** pemeriksaan `user_id`, TTL, dan sekali pakai tetap di
`PendingStore`; otorisasi tetap di `@require_auth`.

**Test baru (6):** valid → berhasil; invalid; milik pengguna lain (token tidak
terhapus); sudah dipakai; kedaluwarsa (ttl=0); tanpa izin ditolak.

## BAGIAN B — Audit Alur Foto (10 butir, dari kode nyata)

| # | Butir | Hasil |
|---|-------|-------|
| 1 | Hanya pengguna berwenang | ✅ `@require_auth` |
| 2 | Kegagalan ekstraksi tanpa mutasi | ✅ `AIProviderError` → `❌`; `_parse_json` gagal → `❌` |
| 3 | Hasil OCR = usulan, bukan fakta | ✅ draf + tombol "Periksa… Simpan?" (konfirmasi) |
| 4 | Identitas/plat divalidasi | ✅ `find_vehicle_by_plate` (normalisasi plat) |
| 5 | Kendaraan lama vs baru | ✅ lama → lanjut; baru → ditolak ("belum terdaftar", tanpa yatim) |
| 6 | Ekstraksi tak lengkap → klarifikasi | ✅ plat kosong/gagal → tolak + arahan manual |
| 7 | Total-only jaga jasa/part tidak diketahui | ✅ tidak ada pengarang rincian; foto tidak mengekstrak total |
| 8 | Perubahan butuh konfirmasi eksplisit | ✅ pending action + tombol konfirmasi |
| 9 | Transaksi atomik | ✅ `add_service_record` satu langkah (kendaraan sudah ada) |
| 10 | Pakai service tepat, tanpa bypass validasi/otorisasi | ✅ `VehicleService`/`ServiceRecordService` |

**Tidak ada bug terbukti pada alur foto → tidak ada perubahan kode.**

**Catatan desain (bukan bug):**
- Alur foto mensyaratkan kendaraan **sudah terdaftar** (tidak membuat kendaraan baru
  dari foto). Ini aman (tanpa kendaraan yatim), tapi pembuatan kendaraan baru dari
  foto adalah fitur di luar cakupan.
- `parts` kosong disimpan sebagai `total_part = 0` (semantik "tidak ada part"),
  sama dengan alur manual `/servis`; bukan pengarang harga.
- Foto "total saja" (tanpa rincian) tidak didukung (prompt ekstraksi meminta
  jobs/parts, bukan total) — hasilnya draf kosong yang tetap butuh konfirmasi.

## BAGIAN C — Test Deterministik (14 baru, mock + DB sementara)

- **Pembatalan (6):** `test_ai_cancel_valid_token_reports_success`,
  `_rejects_invalid_token`, `_rejects_other_user`, `_rejects_used_token`,
  `_rejects_expired_token`, `_denies_unauthorized`.
- **Foto (8):** `test_ai_photo_handler_valid_creates_pending`,
  `_unclear_plate_refuses`, `_new_vehicle_refuses`, `_extraction_empty_refuses`,
  `_extraction_error_refuses`, `_confirm_saves`, `_cancel_no_mutation`,
  `_denies_unauthorized`.

## BAGIAN D — Regresi

- `python -m pytest -q` → **180 passed, 0 failed, 0 skipped** (166 + 14 baru).

## BAGIAN E — Database Operasional

- `data/workshop.db` **tidak berubah** (read-only: 1 kendaraan, 0 servis).
- Tidak ada token/API key tercetak; tidak ada request API/polling nyata.

## Keterbatasan & Rekomendasi

1. Live Gemini (ekstraksi foto nyata) belum diuji — `GEMINI_API_KEY` kosong.
2. Live Telegram E2E tetap belum diuji.
3. (Opsional) dukungan pembuatan kendaraan baru dari foto & "total saja" dari foto.

**Rekomendasi:** uji Gemini bila key tersedia; uji live Telegram satu sesi terkendali.
