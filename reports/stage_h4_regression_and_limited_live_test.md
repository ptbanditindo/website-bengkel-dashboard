# Laporan H4 — Audit Regresi H3 & Live Test Terbatas

## Status Akhir: **PARTIAL PASS**

Audit H3 lolos, 141 test deterministik lulus, dan live test terbatas (tepat 3
request, tanpa retry) **memverifikasi perilaku inti model** (`record_service_visit`
+ konsistensi atomik + total-only). Satu item (tool laporan via live) tidak
dijalankan karena budget 3 request habis — dilaporkan sebagai keterbatasan.

---

## 1. Hasil Audit Implementasi H3

Semua perbaikan H3 **terkonfirmasi ada di kode terkini** (bukan asumsi dari laporan):

| Item | Status | Bukti kode |
|------|--------|-----------|
| Tool `record_service_visit` | ✅ | `ai/tools.py` (schema + plan + executor), `services/service_record_service.py` |
| JSON schema sesuai executor | ✅ | `record_service_visit` schema mencakup nopol/nama/jenis/tahun/wa/alamat/waktu/jobs/parts/garansi/catatan/total |
| System prompt mengarahkan ke tool tsb | ✅ | `SYSTEM_PROMPT` baris "GUNAKAN tool `record_service_visit`" |
| Validasi argumen sebelum mutasi | ✅ | `_plan_record_service_visit` validasi plat & nama client |
| Parsing uang Indonesia | ✅ | `services/pricing.py::parse_money` |
| Transaksi atomik kendaraan+servis | ✅ | `record_service_visit` (satu commit); `execute_pending` atomik |
| Konfirmasi eksplisit sebelum mutasi | ✅ | `PendingStore` + tombol konfirmasi + `execute_pending` |
| Pending action terisolasi/kedaluwarsa/sekali pakai | ✅ | `PendingStore.get/pop` (user-bound, TTL, one-time) |
| Tool laporan via service/repository (bukan SQL model) | ✅ | `services/reporting.py::ReportingService` |
| Perbaikan `write_reports` | ✅ | `tests/live/owner_assistant_50_scenarios.py` (pakai `open()`) |

**Bug baru yang ditemukan: tidak ada.** Tidak ada perubahan kode pada H4 (implementasi H3 sudah benar).

## 2. Test Deterministik (tanpa API)

- **141 passed, 0 failed, 0 skipped** (`python -m pytest -q`).
- Mencakup: pencatatan (kendaraan+servis, total-only, tanpa duplikat, rollback),
  transaksi/konfirmasi (batal, rollback atomik, token sekali pakai, isolasi
  pengguna), query/laporan (semua `ReportingService`), otorisasi, migrasi,
  validasi, dan runner.

## 3. Live API — 3 Request Aktual (tanpa retry)

Model: `deepseek-flash`. Database uji: SQLite sementara terisolasi (dihapus setelahnya).

### Request 1 — Pemetaan instruksi pencatatan ✅ PASS
Instruksi: *"Catat servis hari ini, Avanza 2021 ganti radiator, total semua 600rb. Plat B 3413 FED, nama Budi, WA 081234567890, alamat Bandung."*

- Tool yang dipanggil: **`record_service_visit`** (bukan `create_vehicle` + `add_service_record`).
- Argumen yang diterima (benar):
  - `nopol`: `"B3413FED"` (ternormalisasi) ✅
  - `nama_client`: `"Budi"`, `nomor_wa`: `"081234567890"`, `alamat_client`: `"Bandung"` ✅
  - `jenis_mobil`: `"Avanza"`, `tahun_mobil`: `2021` ✅ (jenis+tahun terpisah benar)
  - `jobs`: `[{"deskripsi": "Ganti radiator"}]` (tanpa harga — benar untuk total-only) ✅
  - `total`: `"600rb"` (diteruskan apa adanya, tidak dipecah) ✅
- **Tidak ada mutasi prematur** sebelum konfirmasi (`no_premature_mutation: true`).

### Request 2 — Konfirmasi & konsistensi mutasi ✅ PASS
Jalur nyata `execute_pending` (0 request API, deterministik):

- Setelah konfirmasi: **1 kendaraan + 1 riwayat servis** (tidak ada kendaraan yatim).
- `total_servis` = `600000.00` (parse `600rb` benar) ✅
- `biaya_jasa` = `None`, `total_part` = `None` (total-only TIDAK mengarang rincian) ✅
- `jobs` = `["Ganti radiator"]`, kendaraan `B3413FED` / Budi / Avanza / 2021 / 081234567890 / Bandung ✅
- Konfirmasi sekali pakai (token terpakai).

### Request 3 — Tool laporan ⏭️ SKIPPED (budget habis)
Tidak dijalankan: Request 1 memakai seluruh 3 request (model melakukan pembacaan
awal + mutasi + jawaban akhir). Tool laporan tetap terverifikasi **secara
deterministik** (test `ReportingService` membuktikan angka cocok dengan fixture).

## 4. Jumlah Request API Aktual

- **3 request** (tepat di batas, tanpa retry, tanpa loop).
- Rincian: seluruhnya dari Request 1 (pembacaan awal + `record_service_visit` + jawaban akhir).

## 5. Verifikasi Database Uji

| Titik | Kendaraan | Servis |
|-------|-----------|--------|
| Sebelum konfirmasi | 0 | 0 |
| Setelah konfirmasi | 1 | 1 |

Total servis `600000.00`; tidak ada kendaraan tanpa servis; tidak ada duplikat.

## 6. Status Database Operasional

- `data/workshop.db` **utuh, tidak diubah** (verifikasi read-only: 1 kendaraan, 0 servis — data lama, dibiarkan).

## 7. Keterbatasan & Pekerjaan Belum Diverifikasi

1. Tool laporan **belum diverifikasi live** (Request 3 dilewati karena budget 3 request).
2. Request 1 memakai 3 request (bukan 2) karena model melakukan pembacaan awal sebelum mutasi — catatan biaya API.
3. Gemini & Telegram end-to-end nyata tetap belum diuji.

## 8. Kesimpulan

- **Inti perbaikan H3 (P1) terverifikasi live**: model memanggil `record_service_visit`
  dengan argumen benar, total-only tidak mengarang rincian, mutasi atomik & konsisten.
- **Tool laporan (P2) terverifikasi deterministik**, belum live (budget).
- Status: **PARTIAL PASS** (bukan PASS penuh karena satu kriteria live belum terverifikasi).
