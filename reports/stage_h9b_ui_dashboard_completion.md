# Laporan H9B — Penyempurnaan UI Dashboard Bengkel

## Status Akhir: **PASS**

UI dilengkapi dengan halaman "Detail Riwayat Servis" khusus yang menampilkan
rincian pekerjaan jasa dan suku cadang (bukan hanya total), serta daftar kendaraan
yang kini menampilkan WhatsApp dan alamat. Tanpa perubahan backend.

---

## 1. Kondisi UI Sebelum Perubahan

- **Dashboard**: sudah menampilkan 3 kartu (total kendaraan, total servis, data
  belum lengkap) + 5 aktivitas terbaru — memadai.
- **Daftar kendaraan**: hanya kolom Plat, Nama, Jenis, Tahun (tanpa WhatsApp/alamat);
  placeholder pencarian "Cari plat nomor…".
- **Detail kendaraan**: identitas + riwayat servis inline (jasa/part sudah dirender
  inline, tapi tidak ada halaman detail servis terpisah).
- **Tidak ada halaman "Detail Riwayat Servis"** — ini kekurangan utama (prioritas).

### Akar penyebab "ganti oli belum tampil"
Bukan karena data tidak tersimpan atau API tidak mengirim data. Bukti (read-only
pada DB operasional hasil pengujian manual Anda):

```
jobs: (1, 1, 'Ganti oli', 1, 470000, 470000)
```

- Data jasa **sudah tersimpan** (deskripsi, jumlah, harga, subtotal).
- API `GET /api/service-records/{id}` **sudah mengembalikan** `jobs`/`parts`.
- Kekurangannya ada di UI: tidak ada halaman detail servis khusus, dan dashboard
  hanya menampilkan total (tanpa rincian pekerjaan). Navigasi ke rincian pekerjaan
  tidak menonjol.

---

## 2. Perubahan yang Diterapkan

| Komponen | Perubahan |
|----------|-----------|
| Halaman "Detail Riwayat Servis" (**baru**) | Menampilkan tanggal, plat, nama, jenis, total, garansi, status klaim, catatan + tabel jasa + tabel part + ringkasan biaya |
| Detail kendaraan | Riwayat servis kini ringkas (tanggal, total, garansi, status klaim, jumlah jasa/part) + tombol **"Lihat Detail"** per servis |
| Daftar kendaraan | Tambah kolom **WhatsApp** dan **Alamat**; pencarian kini berlabel "nama atau plat nomor" |
| Helper & navigasi | `fmtDateOnly` (format tanggal DD-MM-YYYY), delegasi event `data-record` |
| Styling | `.table-scroll`, `.record-actions`, `.ta-r`, `overflow-x` pada `.panel` |

---

## 3. File yang Diubah

| File | Perubahan |
|------|-----------|
| `static/app.js` | +`currentRecordId`, +view `serviceDetail`, +`renderServiceDetail`, +`jobsTable`, +`partsTable`, +`costSummary`, +`fmtDateOnly`; rewrite `recordsHtml`; +kolom WA/Alamat di `vehicleTable`; +handler `data-record` |
| `static/styles.css` | +`.table-scroll`, `.record-actions`, `.ta-r`, `overflow-x` |
| `tests/test_ui.py` | +`test_ui_uses_real_service_record_endpoint` |

Tidak ada perubahan pada `api/`, `services/`, `ai/`, `bot/`, model, atau skema.

---

## 4. Endpoint & Sumber Data yang Digunakan

| Endpoint | Dipakai untuk |
|----------|--------------|
| `GET /api/dashboard` | dashboard |
| `GET /api/vehicles` / `GET /api/vehicles/search?q=` | daftar + pencarian (nama/plat/jenis) |
| `GET /api/vehicles/{id}` | detail kendaraan + isi form edit |
| `GET /api/vehicles/{id}/service-records` | daftar riwayat servis kendaraan |
| `GET /api/service-records/{id}` | **detail riwayat servis (baru dipakai)** |
| `PUT /api/vehicles/{id}` | edit kendaraan |
| `POST /api/admin/backup` / `POST /api/admin/restore` | backup/restore |

Semua endpoint data memakai `Authorization: Bearer <token>`; tidak ada data dummy.

---

## 5. Status Setiap Bagian UI

| Bagian | Status | Catatan |
|--------|--------|---------|
| Dashboard | ✅ | 3 kartu + 5 aktivitas terbaru (dari API) |
| Daftar kendaraan | ✅ | +WA +Alamat, pencarian nama/plat, loading/empty/error |
| Detail kendaraan | ✅ | identitas + riwayat servis + tombol "Lihat Detail" |
| Detail riwayat servis | ✅ | **tabel jasa + tabel part + ringkasan biaya** |
| Edit kendaraan | ✅ (tidak berubah) | update parsial |
| Backup/restore | ✅ (tidak berubah) | — |
| Loading/error/empty | ✅ | setiap tampilan punya state yang jelas |

---

## 6. Kekurangan Backend/API yang Ditemukan

Tidak ada kekurangan yang menghalangi tampilan rincian servis — API sudah
mengembalikan `jobs` dan `parts` lengkap.

Satu pengamatan kecil (bukan penghalang, tidak diubah di H9B): untuk servis yang
direkam tanpa rincian part, kolom `total_part` tersimpan sebagai `0` (bukan `null`)
pada jalur `grand_total`. Akibatnya "Subtotal Suku Cadang" menampilkan `Rp 0`
untuk catatan semacam itu (contoh: servis "Ganti oli" total saja). Rincian jasa
"Ganti oli" sendiri tampil benar dengan harga & subtotal.

---

## 7. Hasil Pengujian Aktual

```
node --check static/app.js                                        -> JS syntax OK
python -m pytest -q                                               -> 267 passed, 0 failed, 0 skipped
Invoke-WebRequest http://127.0.0.1:8000/static/app.js             -> tersaji (27887 B),
                                                                    berisi renderServiceDetail,
                                                                    jobsTable, data-record
```

- Tes baru `tests/test_ui.py::test_ui_uses_real_service_record_endpoint` lulus.
- Data servis (jasa/part) sudah tercakup oleh `tests/test_read_api.py`
  (`test_service_records_for_vehicle` memverifikasi `jobs[0].deskripsi == "Ganti oli"`).

---

## 8. Hasil Pemeriksaan Git

- `static/` dan `tests/` berstatus untracked (pre-existing sejak proyek berkembang).
- Perubahan H9B hanya menyentuh `static/app.js`, `static/styles.css`,
  `tests/test_ui.py`. Tidak ada file backend/konfigurasi yang berubah.

---

## 9. Konfirmasi Database Operasional

`data/workshop.db` **tidak dimodifikasi oleh H9B** (hanya perubahan file statis UI).
Pemeriksaan read-only setelah pekerjaan:

```
vehicles: 3, service_records: 3, service_jobs: 3, service_parts: 1
alembic: c7c0a1b2c3d4, journal_mode: delete
```

Data di atas adalah hasil pengujian manual Anda melalui bot (bukan H9B). Tidak ada
`init_db()`/migrasi/WAL yang dijalankan selama H9B.

---

## 10. Cara Menjalankan & Pemeriksaan Manual

```
python run_api.py          # bila belum berjalan
# buka http://127.0.0.1:8000/ui, login dengan UI_ACCESS_TOKEN
```

Langkah manual:
1. **Dashboard** — lihat 3 kartu + aktivitas terbaru.
2. **Kendaraan** — tabel menampilkan nama, WhatsApp, alamat, plat, jenis, tahun;
   coba cari "dendi" atau "B45654".
3. Buka satu kendaraan → **Detail Kendaraan** → daftar riwayat servis dengan tombol
   **"Lihat Detail"**.
4. Klik "Lihat Detail" → halaman **Detail Riwayat Servis** menampilkan tabel
   **Rincian Pekerjaan Jasa** (mis. "Ganti oli" x1 @ Rp470.000, subtotal Rp470.000),
   **Rincian Suku Cadang**, dan **Ringkasan Biaya**.
5. Uji data kosong: servis tanpa rincian menampilkan "Belum tersedia." secara jujur.

---

**Setelah laporan ini, saya berhenti dan menunggu persetujuan Anda.**

