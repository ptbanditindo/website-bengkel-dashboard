# Laporan H8F — Pembangunan UI Browser Lokal

## Status Akhir: **PASS**

UI browser lokal selesai dan terintegrasi dengan API H8A–H8E tanpa mengubah
backend bisnis, database operasional, maupun migrasi.

---

## 1. File yang Dibuat & Diubah

| File | Aksi | Keterangan |
|------|------|-----------|
| `static/index.html` | **baru** | Shell SPA: halaman login + sidebar + area konten |
| `static/styles.css` | **baru** | Styling dashboard admin (desktop & tablet) |
| `static/app.js` | **baru** | Seluruh logika: login, dashboard, daftar, detail, edit, backup/restore |
| `api/app.py` | **diubah** | Tambah import `FileResponse`/`StaticFiles` + route publik `GET /ui` + `app.mount("/static")` |
| `tests/test_ui.py` | **baru** | 4 test terarah penyajian UI & aset |

**Tidak diubah:** endpoint `/`, `/health`, `/api/*`, `database/*`, service,
repository, model, dan skema.

---

## 2. Fitur UI yang Sudah Berfungsi

- **Login/autentikasi** — input `UI_ACCESS_TOKEN`, disimpan di `sessionStorage`,
  dikirim via header `Authorization: Bearer …` (bukan URL/query). Logout menghapus
  token. Tangani 401 (token salah/sesi habis) dan 503 (token belum dikonfigurasi).
- **Dashboard** — total kendaraan, total riwayat servis, data belum lengkap,
  5 aktivitas servis terbaru (dari `GET /api/dashboard`; tanpa angka contoh).
- **Daftar & pencarian kendaraan** — tabel, pencarian plat (backend menormalkan),
  pagination `limit`/`offset`, tombol Detail, loading/empty/error state.
- **Detail kendaraan** — nama, WhatsApp, plat, jenis, tahun, alamat, status
  kelengkapan, jumlah & rincian riwayat servis (jasa, part, harga, total). Nilai
  kosong ditampilkan "Belum diisi" (jujur, tanpa mengarang).
- **Edit kendaraan** — form terisi data aktual; kirim **hanya field yang berubah**
  (update parsial, `nama_client` tidak dikirim bila tidak diubah); tangani 400/401/
  409/422/503; duplikat plat ditampilkan jelas; setelah sukses muat ulang detail.
- **Backup** — tombol "Buat Backup", tampilkan nama file/ukuran/waktu dari respons API.
- **Restore** — pilih file, konfirmasi eksplisit, peringatan penggantian DB + hentikan
  bot, kirim **raw bytes** (`application/octet-stream`), batas 50 MB, penanganan error.

---

## 3. Endpoint yang Digunakan

| Endpoint | Dipakai untuk |
|----------|--------------|
| `GET /api/dashboard` | kartu dashboard + aktivitas terbaru |
| `GET /api/vehicles` | daftar + pagination |
| `GET /api/vehicles/search?q=` | pencarian plat |
| `GET /api/vehicles/{id}` | detail + isi form edit |
| `PUT /api/vehicles/{id}` | edit (update parsial) |
| `GET /api/vehicles/{id}/service-records` | riwayat servis + rincian jasa/part |
| `POST /api/admin/backup` | buat backup |
| `POST /api/admin/restore` | restore (raw bytes) |

Semua endpoint data menyertakan `Authorization: Bearer <token>`.

---

## 4. Cara Menjalankan UI Secara Lokal

```
# 1. Atur token & konfigurasi di .env (contoh di .env.example):
#    UI_ACCESS_TOKEN=<token rahasia Anda>
#    APP_HOST=127.0.0.1
#    APP_PORT=8000

# 2. Jalankan API (uvicorn):
python run_api.py

# 3. Buka di browser:
http://127.0.0.1:8000/ui
```

Catatan: saat `run_api.py` dijalankan, `init_db()` (lifespan) akan menerapkan
migrasi pending. Ini perilaku yang sudah ada sejak H8A — **bukan** dilakukan oleh
tahap ini.

---

## 5. Cara Memasukkan Token Autentikasi

1. Buka `http://127.0.0.1:8000/ui`.
2. Masukkan nilai `UI_ACCESS_TOKEN` pada halaman login.
3. Klik **Masuk**. Token disimpan di `sessionStorage` (hilang saat tab ditutup).
4. Klik **Keluar** untuk menghapus token.

---

## 6. Hasil Pemeriksaan Terarah yang Dijalankan

```
node --check static/app.js                       -> JS syntax OK
python -m pytest -q                              -> 245 passed, 0 failed, 0 skipped
python -m pytest tests/test_ui.py tests/test_api.py tests/test_api_security.py -q -> 13 passed
```

Pemeriksaan khusus (via FastAPI TestClient, `init_db` dimock):
- `GET /ui` → 200 `text/html`, berisi login shell (tanpa data `nopol`/`vehicle_count`).
- `GET /static/styles.css` → 200; `GET /static/app.js` → 200.
- Shell publik **tidak** memuat data privat atau token tertanam.
- `/api/dashboard`, `/api/vehicles`, `/api/admin/backup`, `/api/admin/restore`
  tetap menolak request tanpa token (401).
- Root `/` tetap terlindungi (test H8B lama lolos).
- Regresi penuh 245 test lolos (tidak ada regresi).

---

## 7. Masalah yang Ditemukan & Perbaikan

1. **Logika diff edit** — versi awal memakai `forEach` sehingga `return` saat tahun
   invalid tidak membatalkan penyimpanan, dan plat kosong bisa terkirim `null`.
   **Perbaikan:** ganti ke loop `for…of`; tahun invalid membatalkan simpan; plat
   kosong di-skip (tidak dikirim).
2. Tidak ada masalah backend. Tidak ada test lama yang diubah.

---

## 8. Risiko / Fitur yang Belum Selesai

1. **Restore lintas proses** — UI menampilkan peringatan "hentikan bot dulu"; UI
   tidak menghentikan bot secara otomatis (sesuai ketentuan).
2. **`nama_client` nullable** — model & API sudah mengizinkan `null`, tetapi skema
   fisik DB operasional masih `NOT NULL` (migrasi pending). Mengosongkan
   `nama_client` di UI akan ditolak DB hingga migrasi `c7c0a1b2c3d4` diterapkan.
3. Upload restore memakai raw bytes (bukan multipart) sesuai kontrak endpoint.
4. Token disimpan di `sessionStorage` — cocok untuk pemakaian lokal, bukan keamanan
   lintas pengguna.

---

## 9. Konfirmasi Database Operasional

`data/workshop.db` **tidak** dimodifikasi. Pemeriksaan read-only setelah pengujian:

```
vehicles: 1, service_records: 0
alembic: fa7fa27bbb86, nama_client notnull: 1, journal_mode: delete
```

Tidak ada `init_db()`/migrasi/WAL yang dijalankan terhadap DB operasional selama H8F.

---

## 10. Konfirmasi Migrasi

Migrasi `c7c0a1b2c3d4_make_nama_client_optional` **tetap pending** (kolom
`nama_client` masih `notnull=1`).

---

## 11. Rekomendasi Langkah Berikutnya

- **Lanjut** ke verifikasi akhir (mis. H8H/H8I) atau uji manual di browser lokal.
- Sebelum produksi: terapkan migrasi `c7c0a1b2c3d4` bila `nama_client` opsional
  benar-benar dibutuhkan, dan pastikan bot dihentikan saat melakukan restore.

