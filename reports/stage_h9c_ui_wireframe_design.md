# Laporan H9C — Wireframe & Spesifikasi Tata Letak UI AI Bengkel

## Status: **PASS** (tahap desain; tanpa perubahan kode/database/migrasi)

Dokumen ini hanya **rancangan**. Tidak ada kode aplikasi, backend, API, database,
konfigurasi, atau migrasi yang diubah pada tahap ini.

---

## 1. Ringkasan Tujuan Desain

Merancang tata letak UI dashboard bengkel yang modern, minimalis, dan mudah
dipindai, berfokus pada:

- Pencarian pelanggan/kendaraan yang cepat.
- Rincian pekerjaan **jasa** dan **suku cadang** yang jelas (fokus utama).
- Navigasi konsisten: Dashboard → Kendaraan → Detail Kendaraan → Detail Servis.
- Responsif (desktop/tablet/seluler) tanpa dependensi baru.

Rancangan mengikuti implementasi yang sudah ada (vanilla HTML/CSS/JS + FastAPI
yang menyajikan `static/`), bukan framework baru.

---

## 2. Kondisi UI Saat Ini (berdasarkan audit read-only)

| Aspek | Kondisi aktual |
|-------|----------------|
| Shell | `static/index.html` + `static/app.js` + `static/styles.css` (SPA tanpa framework) |
| Autentikasi | Halaman login (input token → `sessionStorage` → header `Authorization: Bearer`) |
| Sidebar | **Dashboard**, **Kendaraan**, **Backup & Restore** (3 menu saja) |
| Header | Judul halaman (`#page-title`) + tombol "Keluar" |
| Dashboard | 3 kartu (total kendaraan, total servis, data belum lengkap) + tabel 5 aktivitas terbaru |
| Daftar kendaraan | Tabel: Plat, Nama, WhatsApp, Alamat, Jenis, Tahun + tombol Detail; pencarian nama/plat |
| Detail kendaraan | Identitas + riwayat servis ringkas + tombol "Lihat Detail" per servis |
| Detail servis | **Sudah ada** (H9B): info servis + tabel jasa + tabel part + ringkasan biaya |
| Edit kendaraan | Form update parsial |
| Backup/restore | Tombol backup + restore (raw bytes, konfirmasi) |

**Kesimpulan audit:** sebagian besar fungsi inti sudah ada. H9C merancang penataan
dan penyempurnaan UX (navigasi, hierarki, responsivitas, state) agar lebih rapi —
bukan membangun ulang.

---

## 3. Prinsip Desain yang Direkomendasikan

- **Minimalis profesional**: putih/abu terang, satu warna aksen (biru), merah untuk
  aksi berisiko, hijau untuk sukses.
- **Hierarki jelas**: judul halaman → ringkasan → rincian.
- **Kartu statistik** sederhana; **tabel** rapi dan mudah dipindai.
- **Aksi konsisten**: tombol utama `primary`, sekunder `ghost`, berisiko `danger`.
- **Jarak antarbagian cukup**; tanpa animasi dekoratif.
- **Bahasa Indonesia** untuk semua label, tombol, pesan.
- **Responsif** dengan CSS murni (grid/flexbox + media query), tanpa dependensi.

---

## 4. Struktur Navigasi

```
Login
 └── Dashboard ────────────> (klik angka/tabel) ──> Daftar Kendaraan
       │                                             └──> Detail Kendaraan
       │                                                    └──> Detail Servis
       └── Kendaraan ────────────────────────> Detail Kendaraan ──> Detail Servis
       └── Backup & Restore
```

- **Tombol kembali**: breadcrumb/back selalu ke halaman induk (Detail Servis →
  Detail Kendaraan → Daftar Kendaraan → Dashboard).
- **Menu "Pelanggan" dan "Aktivitas Bot"** pada referensi **tidak ditambahkan**
  karena tidak ada fungsi/sumber data (lihat §13 rekomendasi).

---

## 5. Wireframe Dashboard

### 5.1 Nama & tujuan
**Dashboard** — ringkasan kondisi bengkel dan pintu masuk ke data.

### 5.2 Wireframe ASCII

```text
+---------------------------------------------------------------+
| AI BENGKEL                                      [Keluar]       |
+-------------+-------------------------------------------------+
| DASHBOARD   |  Dashboard                                      |
| Kendaraan   |  +-------------+ +-------------+ +------------+ |
| Backup &    |  | Kendaraan   | | Riwayat     | | Data Belum | |
| Restore     |  |     3       | | Servis   3  | | Lengkap  2 | |
|             |  +-------------+ +-------------+ +------------+ |
|             |                                                 |
|             |  Riwayat Servis Terbaru                         |
|             |  +------------------------------------------+   |
|             |  | Plat    | Pelanggan | Tanggal   | Total |   |
|             |  |---------|-----------|-----------|-------|   |
|             |  | D34...  | Pak Dendi | 15-10-26  | 470rb |   |
|             |  +------------------------------------------+   |
|             |  (baris → klik → Detail Servis)                |
+-------------+-------------------------------------------------+
```

### 5.3 Urutan komponen (atas → bawah)
1. Sidebar (brand + menu).
2. Header (judul + "Keluar").
3. Kartu statistik (3 kartu).
4. Panel "Riwayat Servis Terbaru" (tabel 5 baris).

### 5.4 Posisi & fungsi
- **Kartu statistik**: menampilkan `vehicle_count`, `service_record_count`,
  `incomplete_vehicles_count`. Klik kartu "Kendaraan" → navigasi ke Daftar Kendaraan.
- **Tabel terbaru**: tiap baris (Plat, Pelanggan, Tanggal, Total) **dapat diklik**
  → Detail Servis (pakai `RecentActivityOut.id` = id servis).

### 5.5 Data dari API
`GET /api/dashboard` → `DashboardOut{vehicle_count, service_record_count,
recent_service_records[], incomplete_vehicles_count}`.

### 5.6 Navigasi
Dashboard → (klik tabel) → Detail Servis; (klik kartu Kendaraan) → Daftar Kendaraan.

### 5.7 Desktop / Tablet / Seluler
- Desktop: sidebar tetap, 3 kartu sejajar.
- Tablet: kartu 2 kolom.
- Seluler: sidebar jadi baris atas, kartu 1 kolom, tabel terbaru discroll horizontal.

### 5.8 Loading / kosong / error
- Loading: spinner + "Memuat dashboard…".
- Kosong: kartu tetap menampilkan angka (termasuk 0), tabel menampilkan
  "Belum ada riwayat servis."
- Error: kartu menampilkan "–" dan tabel menampilkan pesan error (bukan data palsu).

### 5.9 Catatan kesesuaian
Sudah 90% sesuai. **Gap**: baris "Riwayat Servis Terbaru" saat ini belum dapat
diklik (kolom tabel tanpa tautan); kartu statistik belum menjadi tautan.

### 5.10 Kekurangan data
Tidak ada sumber "aktivitas sistem" — bagian aktivitas dihilangkan (jujur).

---

## 6. Wireframe Daftar Kendaraan

### 6.1 Nama & tujuan
**Kendaraan** — mencari dan membuka data pelanggan + kendaraan.

### 6.2 Wireframe ASCII

```text
+---------------------------------------------------------------+
| AI BENGKEL                                      [Keluar]       |
+-------------+-------------------------------------------------+
| Dashboard   |  Kendaraan                                      |
| KENDARAAN   |  [ Cari nama atau plat nomor............. ] [Cari] [Reset] |
| Backup &    |                                                 |
| Restore     |  +----------------------------------------------------------+
|             |  | Plat | Pelanggan | WhatsApp | Alamat | Jenis | Tahun | Aksi |
|             |  |------|-----------|----------|--------|-------|-------|------|
|             |  | D... | Pak Dendi | 082...   | Cant.. | Hilux | 2019  | [Detail] |
|             |  +----------------------------------------------------------+
|             |  [Sebelumnya]  Halaman 1  [Berikutnya]          |
+-------------+-------------------------------------------------+
```

### 6.3 Urutan komponen
1. Sidebar. 2. Header. 3. Toolbar pencarian. 4. Tabel kendaraan. 5. Pagination.

### 6.4 Posisi & fungsi
- **Pencarian**: `GET /api/vehicles/search?q=` (mencari nama, plat, jenis).
- **Tabel**: Plat, Pelanggan (`nama_client`), WhatsApp (`nomor_wa`), Alamat
  (`alamat_client`), Jenis (`jenis_mobil`), Tahun (`tahun_mobil`), Aksi "Detail".
- **Pagination**: `limit`/`offset` pada `GET /api/vehicles`.
- **Detail**: tombol → Detail Kendaraan.

### 6.5 Data dari API
`GET /api/vehicles?limit=&offset=` dan `GET /api/vehicles/search?q=`
→ `VehicleSummary{id, nopol, nama_client, nomor_wa, jenis_mobil, tahun_mobil, alamat_client}`.

### 6.6 Navigasi
Daftar → Detail Kendaraan; sidebar → Dashboard/Backup.

### 6.7 Desktop / Tablet / Seluler
- Desktop: 7 kolom lebar.
- Tablet: tabel discroll horizontal (`.table-scroll`).
- Seluler: **kartu bertumpuk** (alternatif) — tiap kendaraan jadi kartu dengan
  baris Plat/Nama/WA/Alamat dan tombol Detail (hindari tabel 7 kolom sempit).

### 6.8 Loading / kosong / error
- Loading: spinner "Memuat…".
- Kosong: "Tidak ada kendaraan." + ajakan menambah (jika relevan).
- Error: pesan error, tetap tampilkan toolbar pencarian.

### 6.9 Catatan kesesuaian
H9B sudah menambah kolom WA + Alamat. **Gap**: belum ada tampilan "kartu" khusus
untuk layar sempit (tabel 7 kolom hanya discroll).

### 6.10 Kekurangan data
Filter terpisah (tahun/jenis) tidak ada di endpoint publik — `q` sudah mencakup
nama/plat/jenis. Filter lanjutan = rekomendasi (butuh endpoint baru).

---

## 7. Wireframe Detail Kendaraan

### 7.1 Nama & tujuan
**Detail Kendaraan** — identitas pelanggan + kendaraan + seluruh riwayat servis.

### 7.2 Wireframe ASCII

```text
+---------------------------------------------------------------+
| AI BENGKEL                                      [Keluar]       |
+-------------+-------------------------------------------------+
| Dashboard   |  Detail Kendaraan                [← Kembali]     |
| KENDARAAN   |                                                 |
| Backup &    |  +----------------------------------------------------------+
| Restore     |  | Pelanggan : Pak Dendi                                   |
|             |  | WhatsApp  : 082117836285                                |
|             |  | Alamat    : Cantayan                                    |
|             |  | Plat      : B45654DFD          [Edit Kendaraan]         |
|             |  | Kendaraan : Hilux 2019                                   |
|             |  +----------------------------------------------------------+
|             |  RIWAYAT SERVIS                                           |
|             |  +--------------------------------------------------------+
|             |  | Tanggal  | Pekerjaan        | Total     | Aksi          |
|             |  |----------|------------------|-----------|---------------|
|             |  | 15-10-26 | Ganti oli        | Rp470.000 | [Detail Servis]|
|             |  | 15-10-26 | Jasa pasang ...  | Rp800.000 | [Detail Servis]|
|             |  +--------------------------------------------------------+
+-------------+-------------------------------------------------+
```

### 7.3 Urutan komponen
1. Sidebar. 2. Header + tombol "Kembali". 3. Kartu identitas. 4. Panel Riwayat Servis.

### 7.4 Posisi & fungsi
- **Kartu identitas**: `nama_client`, `nomor_wa`, `alamat_client`, `nopol`,
  `jenis_mobil` + `tahun_mobil` (digabung "Hilux 2019"), badge kelengkapan,
  tombol "Edit Kendaraan".
- **Riwayat servis**: ringkas per servis (tanggal, ringkasan pekerjaan, total,
  garansi) + tombol **"Detail Servis"**. Ringkasan pekerjaan = daftar deskripsi
  job yang tercatat (bukan hanya satu; mis. "Ganti oli, Cek rem").

### 7.5 Data dari API
`GET /api/vehicles/{id}` → `VehicleDetail{...VehicleSummary, missing_fields,
service_record_count}`; `GET /api/vehicles/{id}/service-records` →
`list[ServiceRecordOut]` (termasuk `jobs[]` untuk ringkasan pekerjaan).

### 7.6 Navigasi
Detail Kendaraan → Detail Servis (per baris); "Kembali" → Daftar Kendaraan;
"Edit" → Edit Kendaraan.

### 7.7 Desktop / Tablet / Seluler
- Desktop: kartu identitas grid 2–3 kolom, tabel riwayat lebar.
- Tablet: identitas 2 kolom.
- Seluler: identitas 1 kolom; riwayat servis jadi kartu bertumpuk (bukan tabel).

### 7.8 Loading / kosong / error
- Loading: "Memuat detail…".
- Kosong riwayat: "Belum ada riwayat servis."
- Error: pesan error + tombol "Kembali ke daftar".

### 7.9 Catatan kesesuaian
Sudah sesuai (H9B). **Gap kecil**: ringkasan "pekerjaan" di tabel riwayat saat ini
hanya jumlah jasa ("1 jasa"), belum menampilkan nama pekerjaannya.

### 7.10 Kekurangan data
Merek/model terpisah tidak ada — hanya `jenis_mobil` + `tahun_mobil` (sudah cukup).

---

## 8. Wireframe Detail Riwayat Servis (PRIORITAS UTAMA)

### 8.1 Nama & tujuan
**Detail Servis** — menampilkan rincian pekerjaan jasa dan suku cadang secara jelas,
bukan hanya total.

### 8.2 Wireframe ASCII

```text
+---------------------------------------------------------------+
| AI BENGKEL                                      [Keluar]       |
+-------------+-------------------------------------------------+
| Dashboard   |  Detail Servis           [← Kembali ke Kendaraan] |
| Kendaraan   |                                                 |
| Backup &    |  INFORMASI SERVIS                                |
| Restore     |  +------------------------------------------------------+
|             |  | Tanggal : 15-10-2026   Total   : Rp470.000         |
|             |  | Pelanggan: Pak Dendi  Plat    : B45654DFD          |
|             |  | Kendaraan: Hilux 2019  Status  : Belum claim       |
|             |  | Garansi  : 18-10-2026  Catatan : -                 |
|             |  +------------------------------------------------------+
|             |  RINCIAN PEKERJAAN JASA                           |
|             |  +------------------------------------------------+
|             |  | Pekerjaan   | Qty | Harga Satuan | Subtotal    |
|             |  |-------------|-----|--------------|-------------|
|             |  | Ganti oli   | 1   | Rp470.000    | Rp470.000   |
|             |  +------------------------------------------------+
|             |  RINCIAN SUKU CADANG                              |
|             |  +------------------------------------------------+
|             |  | Nama        | Qty | Harga Satuan | Subtotal    |
|             |  |-------------|-----|--------------|-------------|
|             |  | Radiator    | 1   | Rp600.000    | Rp600.000   |
|             |  +------------------------------------------------+
|             |  RINGKASAN BIAYA                                 |
|             |  +-------------------------------------+
|             |  | Subtotal Jasa          Rp470.000    |
|             |  | Subtotal Suku Cadang   Rp600.000    |
|             |  | TOTAL                  Rp800.000    |
|             |  +-------------------------------------+
+-------------+-------------------------------------------------+
```

### 8.3 Urutan komponen (atas → bawah)
1. Judul + "Kembali ke Kendaraan".
2. Kartu **Informasi Servis**.
3. Panel **Rincian Pekerjaan Jasa**.
4. Panel **Rincian Suku Cadang**.
5. Panel **Ringkasan Biaya**.

### 8.4 Posisi & fungsi
- **Informasi servis**: `waktu_service`, `total_servis`, identitas kendaraan
  (`vehicle_id` → detail kendaraan), `garansi_sampai`, `status_klaim`, `catatan`.
- **Tabel jasa**: Nama Pekerjaan / Qty / Harga Satuan / Subtotal
  (`jobs[].deskripsi, jumlah, harga, subtotal`).
- **Tabel part**: Nama / Qty / Harga Satuan / Subtotal
  (`parts[].nama_part, jumlah, harga_satuan, subtotal`).
- **Ringkasan biaya**: `biaya_jasa`, `total_part`, `total_servis`.

### 8.5 Data dari API
`GET /api/service-records/{id}` → `ServiceRecordOut`; `GET /api/vehicles/{vehicle_id}`
→ `VehicleDetail` (nama pelanggan & plat, karena `ServiceRecordOut` hanya membawa
`vehicle_id`).

### 8.6 Perilaku saat data bervariasi (wajib)
- **Banyak jasa**: semua baris berurutan; `Subtotal Jasa` = `biaya_jasa`.
- **Banyak part**: semua baris; `Subtotal Suku Cadang` = `total_part`.
- **Tanpa part**: panel part menampilkan **"Belum tersedia."** (bukan `Rp0` palsu).
- **Nilai opsional kosong** (garansi/status/catatan/harga): tampilkan "Belum tersedia"/"–".
- **`harga`/`subtotal` null**: sel tampilkan "–".
- **API gagal**: pesan error + tombol "Kembali"; tidak menampilkan data lama.
- **Sedang dimuat**: spinner "Memuat detail servis…".

### 8.7 Navigasi
Detail Servis → "Kembali ke Kendaraan" → Detail Kendaraan.

### 8.8 Desktop / Tablet / Seluler
- Desktop: panel jasa & part bertumpuk (atau berdampingan 2 kolom); ringkasan biaya di bawah.
- Tablet: 1 kolom, tabel discroll horizontal.
- Seluler: 1 kolom; tabel jasa/part discroll horizontal; ringkasan biaya jadi kartu.

### 8.9 Catatan kesesuaian
H9B **sudah membangun** halaman ini. Rancangan menambahkan: hierarki lebih jelas,
penanganan `null` → "Belum tersedia" konsisten, dan penataan ulang ringkasan biaya.

### 8.10 Kekurangan data
- `ServiceRecordOut` tanpa `nopol`/`nama_client` → UI melakukan 2 pemanggilan
  (record + vehicle). Bisa disederhanakan (opsional) dengan menambah field, bukan keharusan.
- `total_part` kadang tersimpan `0` untuk servis tanpa part → UI disarankan
  menampilkan "Belum tersedia" bila `parts[]` kosong (tanpa mengubah backend).

---

## 9. Wireframe Responsif (Ringkas)

### 9.1 Sidebar
- Desktop (≥ 768px): sidebar kiri tetap (±230px).
- Seluler (< 768px): sidebar jadi **baris atas** (menu horizontal, dapat digulir);
  konten satu kolom.

### 9.2 Tabel
- Desktop: tabel penuh.
- Seluler: Daftar Kendaraan & Riwayat Servis → **kartu bertumpuk** (label: nilai);
  tabel jasa/part di Detail Servis → discroll horizontal.

### 9.3 Kartu statistik
- Desktop: 3 kolom; tablet: 2 kolom; seluler: 1 kolom.

### 9.4 Teks panjang
- Plat: `white-space: nowrap` (tidak terpotong).
- Alamat/catatan: wrap; ellipsis + `title` untuk teks penuh.

---

## 10. Pemetaan Kebutuhan Data → API

| Kebutuhan tampilan | Sumber (field) | Endpoint |
|--------------------|----------------|----------|
| Total kendaraan | `vehicle_count` | `/api/dashboard` |
| Total servis | `service_record_count` | `/api/dashboard` |
| Data belum lengkap | `incomplete_vehicles_count` | `/api/dashboard` |
| Aktivitas terbaru | `recent_service_records[]` | `/api/dashboard` |
| Daftar kendaraan | `VehicleSummary.*` | `/api/vehicles`, `/api/vehicles/search` |
| Identitas kendaraan | `VehicleDetail.*` + `missing_fields` | `/api/vehicles/{id}` |
| Riwayat servis | `ServiceRecordOut[]` (jobs, parts, total, garansi) | `/api/vehicles/{id}/service-records` |
| Detail servis | `ServiceRecordOut` | `/api/service-records/{id}` |
| Nama & plat di detail servis | `VehicleDetail` | `/api/vehicles/{vehicle_id}` |
| Edit kendaraan | `VehicleUpdate` (parsial) | `PUT /api/vehicles/{id}` |

---

## 11. Kondisi Loading / Kosong / Error (standar)

| Keadaan | Perilaku |
|---------|----------|
| Loading | spinner + "Memuat …" di area konten |
| Kosong | pesan informatif spesifik ("Belum ada …") |
| Error API | pesan error (detail API), tombol "Coba lagi"/"Kembali"; TIDAK menampilkan data palsu |
| 401/503 | kembali ke login dengan pesan jelas |

---

## 12. Kesesuaian UI Saat Ini vs Rancangan

| Area | Kondisi Saat Ini | Rancangan Diusulkan | Kesenjangan | Tahap Implementasi |
|------|------------------|---------------------|-------------|--------------------|
| Sidebar | 3 menu (Dashboard, Kendaraan, Backup & Restore) | sama | tidak ada | — |
| Dashboard | 3 kartu + tabel 5 aktivitas | + baris tabel & kartu dapat diklik | kecil (penataan) | berikutnya |
| Daftar kendaraan | tabel 7 kolom + pencarian | + tampilan kartu untuk seluler | kecil (responsif) | berikutnya |
| Detail kendaraan | identitas + riwayat ringkas + "Lihat Detail" | + ringkasan nama pekerjaan di tabel | kecil (penataan) | berikutnya |
| Detail servis | info + jasa + part + ringkasan | + penanganan null→"Belum tersedia" konsisten | kecil | berikutnya |
| Menu Pelanggan | tidak ada | tidak ditambahkan (belum ada fungsi) | rekomendasi | butuh persetujuan |
| Menu Aktivitas Bot | tidak ada | tidak ditambahkan (tanpa sumber data) | rekomendasi | butuh persetujuan |
| Filter tahun/jenis | tidak ada | tidak ditambahkan (butuh endpoint) | rekomendasi | butuh persetujuan |

---

## 13. Kesenjangan Data / API

1. **`ServiceRecordOut` tanpa `nopol`/`nama_client`** — UI memakai 2 panggilan.
   Perubahan minimum (opsional): tambah `nopol` + `nama_client` ke respons
   `GET /api/service-records/{id}` (join kendaraan). Tidak wajib.
2. **`total_part = 0` vs `null`** untuk servis tanpa part — disarankan UI menampilkan
   "Belum tersedia" bila `parts[]` kosong. Tidak mengubah backend.
3. **Tidak ada merek/model terpisah** — hanya `jenis_mobil` + `tahun_mobil`
   (sudah cukup; "Hilux 2019" = jenis + tahun).
4. **Tidak ada endpoint filter tahun/jenis terpisah** — `q` sudah mencakup
   nama/plat/jenis. Filter lanjutan = fitur baru (butuh persetujuan).
5. **Tidak ada sumber "Aktivitas Bot"** — log aktivitas bot tidak tersimpan.
6. **Tidak ada entitas "Pelanggan" terpisah** — nama pelanggan melekat di
   `Vehicle.nama_client` (satu kendaraan = satu pelanggan), sudah sesuai model.

---

## 14. Rekomendasi Implementasi Bertahap (tahap berikutnya)

1. **Murni penataan UI (tanpa backend):** klik baris dashboard → Detail Servis;
   klik kartu statistik → navigasi; ringkasan nama pekerjaan di tabel riwayat;
   tampilan kartu seluler; penanganan "Belum tersedia" konsisten.
2. **Opsional backend minor (butuh persetujuan):** tambah `nopol`/`nama_client`
   pada `ServiceRecordOut`; perbaiki `total_part` null vs 0.
3. **Fitur baru (butuh persetujuan terpisah):** menu "Pelanggan", "Aktivitas Bot",
   filter tahun/jenis.

---

## 15. Risiko & Hal yang Membutuhkan Persetujuan Pengguna

- Perubahan backend/schema (item 13.1, 13.2) **tidak dilakukan** di H9C.
- Menu/fitur baru (Pelanggan, Aktivitas Bot, filter) **memerlukan persetujuan**.
- Semua rancangan memakai data aktual (tanpa data contoh/ dummy).
- Tidak ada pengujian aplikasi yang dijalankan pada tahap ini (desain saja).

---

**Dokumen selesai. Berhenti dan menunggu persetujuan sebelum implementasi.**



