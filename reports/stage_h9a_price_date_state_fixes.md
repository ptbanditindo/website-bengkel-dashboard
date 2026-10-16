# Laporan H9A — Perbaikan Bug Harga, Tanggal Relatif, dan State Proses Servis

## Status Akhir: **PASS**

Ketiga bug diperbaiki pada akar masalahnya, tes regresi ditambahkan, dan seluruh
suite lulus. Database operasional tidak dimodifikasi selama H9A.

---

## 1. Akar Penyebab Tiap Bug (berdasarkan kode)

### Bug A — `470k` tidak dikenali
- Lokasi: `services/pricing.py::parse_money`.
- `_MONEY_MULTIPLIERS` hanya memuat `miliar/milyar/juta/jt/ribu/rb`, **tanpa `k`**.
  Akibatnya `470k` lolos sampai `Decimal("470k")` → `InvalidOperation` →
  `"Harga tidak valid: 470k"`.
- Ini satu-satunya fungsi normalisasi harga (dipakai `validate_price` untuk total,
  jasa, dan part), sehingga perbaikannya berlaku untuk semua jalur.

### Bug B — `hari ini` tidak terselesaikan
- Lokasi: `services/validation.py::coerce_date` / `coerce_datetime`.
- Keduanya hanya menerima `date.fromisoformat` (YYYY-MM-DD). Tidak ada zona waktu,
  tidak ada tanggal relatif, tidak ada `DD-MM-YYYY`.
- Akibatnya `hari ini` ditolak dan bot meminta tanggal absolut; `15-10-2026` juga
  ditolak (bukan ISO).

### Bug C — State percakapan & draft tidak konsisten
- Lokasi: `bot/ai_handlers.py` (confirm/cancel) dan `ai/orchestrator.py::execute_pending`.
- (a) `ConversationHistory` **tidak pernah direset** setelah transaksi selesai
  (konfirmasi berhasil/dibatalkan), sehingga pesan baru masih mewarisi data lama
  (mis. plat `D3414DSD`) dan bisa tercampur dengan transaksi baru.
- (b) `execute_pending` memanggil `pop()` **sebelum** eksekusi; bila penyimpanan
  gagal, draft hilang dan pengguna harus mengetik ulang.

### Tambahan — regresi `test_root_requires_auth` (401 vs 503)
- Lokasi: `tests/live/h4_limited_live_test.py` dan `h5_report_live_test.py`.
- Kedua skrip live memanggil `load_dotenv()` di level modul. Karena namanya cocok
  pola `*_test.py`, pytest mengimpor keduanya saat koleksi, sehingga nilai `.env`
  (termasuk `UI_ACCESS_TOKEN`) bocor ke proses tes. Setelah `.env` diisi token
  (saat aplikasi dijalankan untuk uji manual), tes fail-closed melihat token → 401.

---

## 2. Perbaikan yang Diterapkan

| File | Perubahan |
|------|-----------|
| `services/pricing.py` | Tambah multiplier `("k", Decimal("1000"))` |
| `services/validation.py` | Tambah `WIB` (UTC+7), `parse_date_expression` (relatif, durasi, DD-MM-YYYY), perluas `coerce_date`/`coerce_datetime` |
| `ai/orchestrator.py` | `execute_pending` kini `get` lalu `pop` setelah commit sukses (draft tidak hilang saat gagal) |
| `bot/ai_handlers.py` | Reset `conversations` setelah konfirmasi berhasil dan setelah batal |
| `tests/conftest.py` | `collect_ignore = ["live"]` (skrip live tidak diimpor pytest) |
| `tests/test_h9a_fixes.py` | **baru** — 21 tes regresi |

### Rincian perilaku baru
- Harga: `470k`, `470 K`, `470rb`, `470 ribu`, `470.000`, `470000`, `Rp470.000`,
  `Rp 470.000` → `470000.00`. Nilai internal tetap `Decimal` (bukan teks mentah).
- Tanggal: `hari ini` → tanggal lokal WIB; `kemarin`/`besok`; `N hari|minggu|bulan|tahun`;
  `15-10-2026` dan `2026-10-15` → `date(2026,10,15)`; tanggal tidak valid ditolak.
- State: draft hanya dihapus setelah commit sukses; riwayat percakapan direset
  setelah transaksi selesai sehingga transaksi berikutnya dimulai bersih.

---

## 3. Tes Baru & Hasil Aktual

`tests/test_h9a_fixes.py` (21 tes):

- **Harga (12):** `parse_money` untuk 8 format Indonesia; `validate_price("470k")`;
  harga tidak valid ditolak; `test_price_survives_date_fix` (perbaikan tanggal tidak
  merusak harga `470k` → tersimpan `470000.00`).
- **Tanggal (9):** `hari ini`, `kemarin`/`besok`, `15-10-2026`, ISO, durasi relatif,
  `coerce_datetime("hari ini")`, tanggal tidak valid (`2026-02-30`, `32-13-2026`).
  Semua tanggal memakai waktu terkontrol (monkeypatch `_today_wib`), bukan jam nyata.
- **State (3):** konfirmasi mereset history; batal mereset history; `execute_pending`
  mempertahankan draft saat gagal.

Perintah yang dijalankan:
```
python -m pytest tests/test_h9a_fixes.py tests/test_pricing.py -q   -> 43 passed
python -m pytest -q                                               -> 266 passed, 0 failed, 0 skipped
```

### Jumlah tes
| | Jumlah |
|--|--------|
| Sebelum H9A (H8F) | 245 |
| Setelah H9A | **266** (245 + 21 baru) |

---

## 4. Risiko yang Belum Diselesaikan

1. **Koreksi dalam satu transaksi masih bergantung pada LLM.** Reset history
   setelah transaksi selesai mencegah kontaminasi antartransaksi (plat lama dipakai
   di transaksi baru). Namun, koreksi field di tengah transaksi yang sama tetap
   mengandalkan DeepSeek mengekstrak ulang dari history. Perbaikan penuh butuh
   draft state machine terstruktur — di luar cakupan "perubahan minimal".
2. **`garansi N hari`** sudah didukung (`3 hari` → +3 hari), tetapi bila AI mengirim
   string berawalan "garansi" (mis. `garansi 3 hari`) parser tetap menolak. System
   prompt sudah menginstruksikan AI memakai `YYYY-MM-DD` untuk `garansi_sampai`.
3. Tidak ada panggilan live AI/Telegram yang dilakukan selama pengujian otomatis.

---

## 5. Konfirmasi Database Operasional

`data/workshop.db` **tidak dimodifikasi selama H9A**. Pemeriksaan read-only
(`file:...?mode=ro`) setelah seluruh pengujian:

```
vehicles: 1, service_records: 0
alembic: c7c0a1b2c3d4, nama_client notnull: 0, journal_mode: delete
```

Tidak ada `init_db()`/migrasi/WAL terhadap DB operasional selama H9A.

## 6. Konfirmasi Status Migrasi

Catatan jujur: migrasi `c7c0a1b2c3d4_make_nama_client_optional` **sudah diterapkan
sebelum H9A** — tepatnya saat aplikasi dijalankan untuk pengujian manual atas
permintaan Anda (perilaku `init_db()` pada startup, bukan oleh H9A). Selama H9A
**tidak ada migrasi yang dijalankan**. Kondisi saat ini terverifikasi:
`alembic = c7c0a1b2c3d4`, `nama_client notnull = 0` (nullable).

---

## 7. Instruksi Pengujian Manual Berikutnya

Ulangi skenario bug (setelah me-restart bot agar memuat kode baru):

1. Kirim: `hilux 2019, plat d 3414 dsd, ganti oli` → bot meminta nama pelanggan.
2. Kirim: `pak dendi, 082117836285, cantayan, hari ini, 470k, garansi 3 hari`
   → ringkasan menampilkan **Tanggal: 15-10-2026** (bukan "hari ini") dan
   **Total: Rp470.000** (bukan teks mentah).
3. Klik **✅ Konfirmasi** (atau kirim jawaban) → tersimpan tanpa meminta tanggal
   absolut dan tanpa error harga.
4. Mulai transaksi baru dengan plat lain (mis. `D3414DSEW`) → pastikan bot tidak
   memakai plat/identitas transaksi sebelumnya.

Jika memakai input teks `benar` (bukan tombol), perilaku tetap bergantung pada
pemahaman DeepSeek; tombol konfirmasi adalah jalur yang deterministik.

