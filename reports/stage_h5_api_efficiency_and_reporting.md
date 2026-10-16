# Laporan H5 — Audit Efisiensi API & Verifikasi Tool Laporan

## Status Akhir: **PASS**

Seluruh kriteria H5 terverifikasi: efisiensi API dianalisis dari kode nyata,
jalur executor tool laporan diverifikasi deterministik, live test 1 skenario
laporan berhasil (2 request), regresi lulus, dan database operasional tidak berubah.

---

## BAGIAN A — Audit Efisiensi API

### Alur satu instruksi pencatatan (dari H4: 3 request model)

Telaah kode `ai/orchestrator.py::handle_message`:

| # | Jenis | Isi | Request API | Tool call model | Eksekusi Python lokal | Mutasi DB |
|---|-------|-----|:-----------:|:---------------:|:----------------------:|:---------:|
| 1 | Pembacaan awal | model memanggil `search_vehicle_by_plate` (pilihan model) | ya | ya | `find_vehicle_by_plate` (read) | tidak |
| 2 | Mutasi direncanakan | model memanggil `record_service_visit` | ya | ya | `_plan_record_service_visit` (validasi + ringkasan) | tidak |
| 3 | Jawaban akhir | model menghasilkan teks akhir | ya | tidak | — | tidak |

**Pemisahan tegas:**
- **Pemanggilan API model:** 3 (tiap `provider.chat()`).
- **Tool call dari model:** 2 (1 read + 1 mutasi).
- **Eksekusi fungsi Python lokal:** validasi/ringkasan `plan_tool`, eksekusi read.
- **Mutasi database:** **hanya** setelah konfirmasi eksplisit (`execute_pending`) — bukan di `handle_message`.

### Temuan efisiensi

1. **Request 3 (jawaban akhir) terbukti terbuang.** Saat `pending_steps` tidak
   kosong, orchestrator mengembalikan `summary` (bukan `content` model), sehingga
   teks akhir model **tidak pernah dipakai**.
2. **Request 1 (pembacaan awal)** adalah pilihan model. `SYSTEM_PROMPT` sudah
   mengarahkan langsung ke `record_service_visit` (yang menangani get-or-create),
   tetapi model tetap memilih membaca dulu — perilaku model, bukan paksaan kode.

### Peluang optimasi & keputusan

- **Peluang:** hentikan loop setelah mutasi terkumpul (hemat 1 request).
- **Risiko:** dapat **kehilangan mutasi berikutnya** pada alur multi-langkah
  (legacy `create_vehicle` + `add_service_record` lintas respons), yang berarti
  "kehilangan argumen tool".
- **Keputusan:** **tidak diterapkan** (belum terbukti aman). Temuan didokumentasikan
  tanpa perubahan kode, sesuai aturan "jangan optimasi jika berisiko".
- **Catatan biaya:** satu pencatatan kini ~2–3 request (2 jika model langsung
  memakai `record_service_visit`, 3 jika model membaca dulu).

## BAGIAN B — Verifikasi Tool Laporan (deterministik, tanpa API)

Ditambahkan `tests/test_report_tools.py` (11 test). Memverifikasi **registrasi +
jalur `plan_tool`/orchestrator**, bukan hanya `ReportingService`.

- **Konsistensi registrasi:** setiap nama di `TOOL_SCHEMAS` punya handler di
  `_PLAN_HANDLERS`; setiap tool mutasi punya `_EXECUTORS`.
- **Read-only:** 9 tool laporan + `search_service_records_by_job` TIDAK ada di
  `MUTATION_TOOLS`/`_EXECUTORS` (tidak butuh konfirmasi).
- **Executor membaca sesi uji yang sama:** hasil `plan_tool` cocok dengan fixture.
- **Angka cocok fixture:** `count_vehicles`=2, `count_service_records`=3,
  `report_service_totals`=Rp700.000, `report_top_jobs` (Ganti oli 2x, Ganti radiator 1x),
  `report_activity_summary`, `search_service_records_by_job`.
- **Pencarian jenis/tahun:** `search_vehicles` dengan `jenis_mobil`/`tahun_mobil` benar.
- **Data kosong:** respons tepat (0 / "Belum ada …" / "Tidak ada kendaraan dalam garansi").
- **Otorisasi:** tool laporan hanya dapat diakses lewat handler chat AI yang
  di-`@require_auth` (otorisasi di lapisan handler Telegram, sesuai arsitektur).

Tool yang diverifikasi: `count_vehicles`, `count_service_records`,
`report_service_totals`, `report_period_summary`, `report_top_jobs`,
`report_vehicles_under_warranty`, `report_part_usage`, `report_activity_summary`,
`search_service_records_by_job`, plus `search_vehicles` (jenis/tahun).

## BAGIAN C — Live Test Laporan (1 skenario)

- **Model:** `deepseek-flash`. **Database:** SQLite sementara terisolasi (dihapus).
- **Pertanyaan:** "Berapa jumlah kendaraan dan jumlah riwayat servis yang tercatat di database ini?"
- **Fixture:** 2 kendaraan, 3 riwayat servis.
- **Tool yang dipilih model:** `count_vehicles` (`{}`) dan `count_service_records` (`{}`) — **benar**.
- **Jawaban model:** "2 kendaraan, 3 riwayat servis" — **cocok dengan fixture**.
- Model **tidak menghitung sendiri**; memakai tool. Tidak ada mutasi (read-only).
- **Jumlah request API aktual: 2** (1× tool call + 1× jawaban akhir), tanpa retry.

## BAGIAN D — Regresi & Keamanan

- `python -m pytest -q` → **152 passed, 0 failed, 0 skipped** (141 + 11 baru).
- Terkonfirmasi tetap: tidak ada mutasi sebelum konfirmasi; pending action
  terisolasi per pengguna; token sekali pakai & kedaluwarsa; rollback atomik;
  total-only menjaga `biaya_jasa`/`total_part` = tidak diketahui.
- Database operasional `data/workshop.db` **tidak berubah** (read-only: 1 kendaraan,
  0 servis).
- Tidak ada token/API key tercetak di log maupun laporan.

## BAGIAN E — Kesimpulan & Rekomendasi

| Kriteria H5 | Status |
|-------------|--------|
| Test deterministik lulus | ✅ 152 |
| Jalur executor tool laporan diverifikasi tanpa API | ✅ |
| Efisiensi API dianalisis dari kode nyata | ✅ (didokumentasikan, tanpa optimasi berisiko) |
| Tanpa mutasi prematur/regresi | ✅ |
| Database operasional tidak berubah | ✅ |
| Live test dalam batas | ✅ 1 skenario, 2 request |
| Keterbatasan dicatat jujur | ✅ |

**Rekomendasi tahap selanjutnya:**
1. Jika biaya API kritis, pertimbangkan optimasi "hentikan loop setelah mutasi
   terkumpul" **dengan pengaman** (hanya untuk `record_service_visit`, yang
   memang satu langkah atomik), lalu regresi penuh.
2. Uji Gemini (ekstraksi gambar) bila `GEMINI_API_KEY` tersedia.
3. Telegram end-to-end nyata dengan akun pemilik.
