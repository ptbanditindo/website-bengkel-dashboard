# Laporan H3 — Perbaikan Terintegrasi AI Bengkel Telegram

## Status Akhir: **PARTIAL PASS**

Perbaikan kode dan pengujian deterministik **selesai dan lulus**. Akurasi model
live (akar masalah H2-1) **belum diuji ulang dengan API nyata** (dihemat sesuai
instruksi); kebutuhan live test tersisa dicatat untuk persetujuan.

---

## 1. Akar Masalah Terkonfirmasi (dari kode, bukan dugaan)

| ID | Akar masalah | Bukti |
|----|--------------|-------|
| H2-1 | `validate_price` memakai `Decimal(str(value))` → gagal untuk `600rb`/`Rp600.000`/`1,5 juta`. Tidak ada parser uang Indonesia. | `services/validation.py` lama; test `test_parse_money_*` |
| H1/H2-2 | `create_vehicle` & `add_service_record` **commit terpisah**; `execute_pending` menjalankan step per-step tanpa rollback gabungan → kendaraan bisa tersimpan tanpa servis. Tidak ada operasi gabungan atomik. | `services/vehicle_service.py`, `services/service_record_service.py`, `ai/orchestrator.py` lama; DB operasional punya 1 kendaraan & 0 servis |
| H2-3 | Tidak ada tool laporan/agregasi; `search_vehicles` hanya cocokkan nama/plat; tidak ada pencarian by pekerjaan. | `ai/tools.py` lama (10 tool) |
| H2-4 | `write_reports` JSON memakai `Path` sebagai file. | Sudah diperbaiki (dipertahankan) |

**Dugaan yang belum terbukti (bukan dianggap bug terkonfirmasi):** akurasi
pemetaan argumen model DeepSeek (mis. memisah "Avanza 2021" → jenis+tahun) —
hanya bisa dibuktikan lewat live API yang belum dijalankan ulang.

## 2. File yang Diubah & Alasan

| File | Perubahan | Alasan |
|------|-----------|--------|
| `services/pricing.py` | Tambah `parse_money` (format uang Indonesia) | H2-1 |
| `services/validation.py` | `validate_price` pakai `parse_money` | H2-1 |
| `services/service_record_service.py` | Tambah `record_service_visit` (atomik); `commit` param; total-only jaga breakdown tetap tidak diketahui | H1/H2-2 |
| `services/vehicle_service.py` | `commit` param; `search_vehicles_filtered` | H2-2/H2-3 |
| `repositories/vehicle_repository.py` | `search_filtered` (nama/plat/jenis/tahun) | H2-3 |
| `services/reporting.py` | **Baru** — `ReportingService` (agregasi) | H2-3 |
| `ai/tools.py` | Prompt baru; tool `record_service_visit`; 9 tool baca laporan; executor `commit=False` | H1/H2-1/H2-3 |
| `ai/orchestrator.py` | `execute_pending` atomik (commit sekali, rollback gabungan) | H1/H2-2 |
| `tests/*` | Tambah 25 test deterministik | validasi |

## 3. Ringkasan Perbaikan

- **Pencatatan servis kini satu tool atomik** `record_service_visit`: membuat
  kendaraan (jika perlu) + riwayat servis dalam **satu transaksi**.
- **`execute_pending` atomik**: gagal di langkah mana pun → seluruh aksi
  di-rollback (tidak ada kendaraan tanpa servis).
- **Nominal Indonesia** (`600rb`, `Rp600.000`, `1,5 juta`) dinormalisasi di Python.
- **Total-only** tidak lagi memecah nominal; biaya jasa/part yang tak diketahui
  tetap `NULL` (bukan nol).
- **Tool laporan** (`count_vehicles`, `count_service_records`, `report_service_totals`,
  `report_period_summary`, `report_top_jobs`, `report_vehicles_under_warranty`,
  `report_part_usage`, `report_activity_summary`, `search_service_records_by_job`)
  dan pencarian by jenis/tahun.

## 4. Hasil Test Deterministik (tanpa API)

- **141 passed, 0 failed, 0 skipped** (`python -m pytest -q`).
- Tambahan 25 test baru meliputi: `parse_money`, `record_service_visit`
  (buat kendaraan+servis, total-only, tanpa duplikat, rollback), rollback atomik
  orchestrator, dan seluruh `ReportingService`.

## 5. Hasil Live API

- **Tidak dijalankan** (penghematan API sesuai instruksi).
- **Jumlah request API aktual pada tahap H3: 0.**
- Kebutuhan live test tersisa (untuk persetujuan pengguna):
  1. Satu pesan lengkap "Catat servis … Avanza 2021 ganti radiator total 600rb …"
     → verifikasi model memanggil `record_service_visit` (bukan dua tool).
  2. Satu pesan nominal "600rb"/"1,5 juta" → verifikasi tersimpan benar.
  3. Satu query laporan → verifikasi angka sesuai DB.

## 6. Verifikasi Konsistensi Kendaraan & Riwayat Servis (deterministik)

- `record_service_visit` pada plat baru → 1 kendaraan + 1 servis (test lulus).
- Plat lama → 1 kendaraan, servis baru ditambah (tanpa duplikat).
- Kegagalan servis → kendaraan baru ikut di-rollback (0 kendaraan, 0 servis).
- Konfirmasi ganda → token sekali pakai (existing test `test_pending_store_one_time`).

## 7. Verifikasi Query & Laporan (deterministik)

- Pencarian by plat/nama/jenis/tahun → `search_filtered` (test lulus).
- Pencarian by pekerjaan → `search_records_by_job` (test lulus).
- Count/sum/rekap/top jobs/garansi/part → `ReportingService` (test lulus).
- Nilai tak diketahui tidak diubah jadi nol (test `test_service_totals_unknown_becomes_none`).

## 8. Status Database Operasional

- `data/workshop.db` **utuh, tidak diubah** (verifikasi read-only).
- Isi saat audit: 1 kendaraan, 0 riwayat servis — **bukti nyata** masalah
  "kendaraan tanpa servis" (Bug H1) yang kini dicegah oleh `record_service_visit`.
  **Tidak dilakukan** migrasi/perbaikan data pada DB operasional (di luar cakupan).

## 9. Bug yang Belum Selesai

1. **Akurasi model live belum diuji ulang** (butuh API; dihemat).
2. Gemini (ekstraksi gambar) belum diuji (key kosong).
3. Telegram end-to-end nyata belum diuji (butuh interaksi pemilik).
4. DB operasional masih menyimpan 1 kendaraan tanpa servis (data lama; tidak disentuh).

## 10. Batasan Pengujian

- Semua pengujian H3 bersifat **deterministik lokal** (fixture, fake provider,
  SQLite in-memory) — **bukan** pengujian kemampuan model.
- Hasil H2 (50 status) dinyatakan **belum terverifikasi** (lihat `stage_h2_clarification.md`).
- Tidak ada live test otomatis besar; tidak ada permintaan API pada tahap ini.

## 11. Kesimpulan

- Kriteria deterministik (validasi, konsistensi, total-only, konfirmasi, laporan,
  suite lulus, DB utuh) **terpenuhi**.
- Kriteria live (akurasi model) **belum diverifikasi ulang**.
- Status: **PARTIAL PASS** — siap untuk live test terbatas setelah disetujui.
