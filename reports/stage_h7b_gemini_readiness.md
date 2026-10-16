# Laporan H7B — Audit Kesiapan Gemini & Foto

## Status Akhir: **PARTIAL PASS**

Seluruh pemeriksaan deterministik lulus (189 test) dan satu perbaikan kecil
diterapkan (cross-check total nota). **Kemampuan OCR Gemini pada foto nyata belum
diuji** (`GEMINI_API_KEY` kosong), sehingga tidak diberi status PASS penuh.

---

## BAGIAN A — Audit Konfigurasi Provider

| Butir | Hasil | Bukti |
|-------|-------|-------|
| DeepSeek provider utama teks | ✅ | `ai/providers.py` `DeepSeekProvider.chat`; orchestrator memakai DeepSeek |
| Gemini hanya untuk gambar | ✅ | `GeminiImageProvider.extract` dipakai hanya di `ai_photo_handler` |
| Kedua key boleh kosong tanpa crash | ✅ | `configured` = `bool(api_key)`; impor/tests tidak memanggil API |
| Provider tak terkonfigurasi → error terkendali | ✅ | chat/photo handler cek `configured` → balasan jelas |
| Tanpa fallback API tambahan diam-diam | ✅ | tidak ada retry/fallback ke provider lain |
| Error tidak membocorkan kredensial | ✅ | hanya `logger.error(... exc)`; key tidak pernah dicetak |
| Tanpa API live pada test deterministik | ✅ | semua test memakai mock provider |
| `GEMINI_API_KEY` kosong → foto gagal aman | ✅ | `ai_photo_handler` balas "belum tersedia", tanpa mutasi |

Status key: `DEEPSEEK_API_KEY` = tersedia, `GEMINI_API_KEY` = **kosong** (nilai tidak ditampilkan).

## BAGIAN B — Audit Alur Foto (10 butir)

| # | Butir | Hasil |
|---|-------|-------|
| 1 | Foto ke provider gambar yang benar | ✅ `runtime.gemini.extract(...)` |
| 2 | Format & ukuran aman | ✅ cek >5MB, non-JPEG ditolak |
| 3 | Respons kosong/JSON invalid tanpa mutasi | ✅ `_parse_json` gagal → `❌`, tidak ada mutasi |
| 4 | Timeout/gagal provider → pesan jelas | ✅ `AIProviderError` → `❌` + arahan manual |
| 5 | Plat dinormalisasi & dicocokkan | ✅ `find_vehicle_by_plate` (normalisasi) |
| 6 | Hasil ekstraksi = draf, bukan fakta | ✅ tombol "Periksa… Simpan?" |
| 7 | Konfirmasi sebelum simpan | ✅ pending action + konfirmasi |
| 8 | Tanpa retry otomatis/panggilan tambahan | ✅ tidak ada loop/retry |
| 9 | Harga tak diketahui tidak dikarang | ✅ harga None → `biaya_jasa`/`total_servis` tidak diketahui |
| 10 | Jalur error menjaga otorisasi & integritas DB | ✅ `@require_auth` + rollback atomik |

## BAGIAN C — Contoh Nota DAVA RADIATOR (ground truth, mock)

Fixtures di `tests/test_photo_draft.py`; **bukan** foto asli, **bukan** hasil OCR Gemini.

- Empat rincian dipertahankan (3 jasa + 1 part, nama sesuai aslinya): total Rp1.825.000.
- `_sum_item_prices` = Rp575.000 + Rp200.000 + Rp275.000 + Rp775.000 = **Rp1.825.000** ✅.
- **Perbaikan diterapkan:** `_build_service_draft` kini mengekstrak `total` (bila ada) dan
  mencocokkannya dengan jumlah rincian; jika tidak cocok menampilkan ⚠️ (murni diagnostik —
  penyimpanan tetap menghitung dari rincian, tidak memakai total hasil OCR).
- Prompt `IMAGE_EXTRACTION_PROMPT` diperluas dengan kunci `total`.

## BAGIAN D — Test Deterministik (9 baru, tanpa API)

`tests/test_photo_draft.py` (8) + 1 handler test:
- struktur 4 item dipertahankan; total cocok; total tidak cocok terdeteksi;
  item hilang; harga invalid → sum None; tanpa total → tanpa baris cross-check;
  `parse_money` format nota; foto harga invalid → konfirmasi gagal + rollback (0 servis).

## BAGIAN E — Regresi

- `python -m pytest -q` → **189 passed, 0 failed, 0 skipped** (180 + 9 baru).

## BAGIAN F — Database Operasional

- `data/workshop.db` **tidak berubah** (read-only: 1 kendaraan, 0 servis).
- Contoh nota hanya dipakai sebagai fixture; **tidak ada** catatan servis nyata yang dibuat.

## Pemisahan Bukti

- **Mock/fixture:** memverifikasi logika struktur, total, dan keamanan alur — bukan kemampuan OCR.
- **OCR Gemini live:** **belum diuji** (key kosong). Contoh nota teks **bukan** bukti OCR berhasil.

## Keterbatasan

1. OCR Gemini pada foto nyata belum diuji (key kosong).
2. Alur foto tetap mensyaratkan kendaraan sudah terdaftar (tidak membuat kendaraan baru).
3. (Catatan kecil, tidak diperbaiki) balasan konfirmasi memakai header "✅ Berhasil" walau
   `execute_pending` bisa mengembalikan "❌ Gagal" — isu UX umum, bukan spesifik foto.

## Rekomendasi

1. Uji Gemini (foto nota nyata) bila `GEMINI_API_KEY` tersedia.
2. Pertimbangkan dukungan pembuatan kendaraan baru dari foto.
