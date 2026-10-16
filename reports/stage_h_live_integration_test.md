# Laporan Live Integration Test — AI Bengkel Telegram

## Waktu Pengujian
- 14 Oktober 2026 (waktu lokal mesin penguji)

## Provider & Model yang Diuji
| Provider | Model | Status |
|----------|-------|--------|
| DeepSeek | `deepseek-flash` | ✅ Diuji (API nyata) |
| Gemini | `gemini-3.8-flash` | ⏭️ SKIPPED — NOT CONFIGURED |

## Status Konfigurasi (tanpa nilai rahasia)
| Variabel | Status |
|----------|--------|
| `TELEGRAM_TOKEN` | SET |
| `AUTHORIZED_USER_ID` | SET |
| `DEEPSEEK_API_KEY` | SET |
| `DEEPSEEK_MODEL` | SET (`deepseek-flash`) |
| `GEMINI_API_KEY` | EMPTY |
| `GEMINI_MODEL` | SET (`gemini-3.8-flash`) |
| `DATABASE_URL` | SET |
| `APP_HOST` / `APP_PORT` | SET |

Nama variabel di `.env` **sesuai** dengan yang dibaca kode (`ai/providers.py`, `database/session.py`).

## Jumlah Request API
- DeepSeek: **5 request** (1 teks, 1 tool-call smoke, 1 turn klarifikasi, 2 turn mutasi).
- Gemini: **0 request** (key kosong).
- Total: 5 request (terbatas, tanpa loop/retry massal).

## Hasil Smoke Test

### DeepSeek — Teks
- Status: ✅ PASS
- Waktu respons: ~3.37 detik
- Model: `deepseek-flash`
- Isi respons valid (panjang 4 karakter, sesuai permintaan "satu kata").

### DeepSeek — Tool Calling
- Status: ✅ PASS
- Waktu respons: ~1.41 detik
- Tool yang dipanggil: `search_vehicle_by_plate`
- Argumen terparsing benar: `{"nopol": "B 1234 XYZ"}`

### Gemini
- Status: ⏭️ SKIPPED — `GEMINI_API_KEY` kosong.

## Hasil Skenario Alur (Orkestrator + DB terisolasi)

Percakapan simulasi (data fiktif):
1. `tambah servis hari ini, Avanza 2021 ganti radiator total 600000`
2. `B 1234 XYZ, Budi, WA 081234567890, alamat Bandung, total semua`

| Langkah | Hasil | Catatan |
|---------|-------|---------|
| Turn 1 — meminta data wajib | ✅ PASS | AI meminta nomor polisi & nama pelanggan (tidak mengarang) |
| Turn 2 — menyiapkan tindakan | ❌ FAIL | AI hanya memanggil `create_vehicle`, TIDAK memanggil `add_service_record` |
| Konfirmasi eksplisit | ✅ PASS | Pending action terbentuk, tidak ada mutasi sebelum konfirmasi |
| Eksekusi setelah konfirmasi | ⚠️ PARTIAL | Hanya kendaraan yang dibuat; servis tidak dicatat |

## Bukti Verifikasi Database (read-only)
Setelah konfirmasi simulasi (DB uji terisolasi, bukan `data/workshop.db`):
- Kendaraan `B1234XYZ`: **1 record** ✅
  - Nama: `Budi` ✅
  - WA: `081234567890` ✅
  - Alamat: `Bandung` ✅
  - Jenis: `Avanza` ✅
  - Tahun: `2021` ✅
- Riwayat servis penggantian radiator: **0 record** ❌ (seharusnya 1)
- Total servis `600000`: ❌ tidak tersimpan (tidak ada servis)
- `biaya_jasa`/`total_part`: tidak dapat diverifikasi (tidak ada servis)
- Duplikat kendaraan: tidak ada ✅
- Data sebelum konfirmasi: 0 kendaraan, 0 servis ✅ (tidak ada mutasi prematur)

## Bug yang Ditemukan

### Bug H1 (P1) — Permintaan gabungan kendaraan+servis tidak menyelesaikan servis
- **Lokasi:** `ai/orchestrator.py` (`handle_message`), `ai/tools.py` (`SYSTEM_PROMPT`), interaksi model.
- **Gejala:** Saat pengguna meminta "tambah kendaraan + servis" dalam satu pesan, model DeepSeek hanya memanggil `create_vehicle`, lalu berhenti setelah menerima umpan balik "[Menunggu konfirmasi]". Model tidak melanjutkan memanggil `add_service_record`.
- **Akar masalah (analisis, belum diperbaiki):**
  1. Mekanisme orkestrator sudah mendukung multi-langkah (Tahap G) — terbukti dari tes unit `test_handle_message_collects_combined_mutations`.
  2. Namun **instruksi sistem dan/atau umpan balik tool belum cukup memandu model** untuk melanjutkan operasi gabungan. Model menganggap `create_vehicle` sudah cukup dan menghasilkan ringkasan akhir.
- **Bukti:** output live test `steps: ['create_vehicle']` dan `service count: 0`.
- **Saran perbaikan (untuk persetujuan):** perkuat `SYSTEM_PROMPT` dan deskripsi tool agar model memahami bahwa servis untuk kendaraan baru = `create_vehicle` + `add_service_record`; atau ubah umpan balik tool agar model diminta menyebutkan langkah berikutnya.

## Tes yang Dilewati
- **Gemini (teks & gambar):** SKIPPED — key kosong.
- **Telegram end-to-end nyata:** belum dilakukan oleh asisten (membutuhkan interaksi manual pemilik akun). Konfigurasi bot sudah diverifikasi (token SET, tanpa dicetak).

## Error Tersanitasi
- Tidak ada error API. Semua request DeepSeek berhasil.
- (Error `ModuleNotFoundError: No module named 'ai'` terjadi sekali pada percobaan pertama skrip karena path — sudah diperbaiki dengan menambah root proyek ke `sys.path`; bukan error aplikasi.)

## Status Akhir
**PARTIAL PASS**

- ✅ DeepSeek teks & tool calling nyata berfungsi.
- ✅ Konfirmasi eksplisit & tidak ada mutasi prematur.
- ❌ Alur gabungan kendaraan+servis belum menyelesaikan servis (Bug H1).
