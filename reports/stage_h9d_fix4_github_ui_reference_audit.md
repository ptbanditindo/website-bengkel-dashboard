# Laporan H9D-FIX4 — Pemeriksaan Referensi GitHub Vehicle Service Center

## Status: **PASS** (audit selesai; tanpa perubahan kode/database)

Repository referensi dikloning (depth 1) ke folder sementara di luar proyek
(`%TEMP%\vsc_ref`) untuk inspeksi. Tidak ada file proyek AI Bengkel yang diubah.

---

## 1. File & Halaman Referensi yang Benar-benar Diperiksa

| File | Isi |
|------|-----|
| `README.md` | arsitektur (Flask + MySQL 18 tabel), fitur, dua frontend, cara pakai |
| `frontend/style.css` (penuh) | nav teal `#0d9488`, modal, action button, toast, empty state |
| `frontend/index.html` (sebagian) | top nav 18 tab CRUD, tabel generik, modal add/edit |
| `frontend-react/src/index.css` (penuh) | tema "Digital Wellness" (sage/lavender/peach), blob + noise + animasi |
| `frontend-react/src/pages/Dashboard.jsx` (penuh) | hero header, 6 kartu statistik, quick actions, info banner |
| `frontend-react/src/pages/TablePage.jsx` (sebagian) | tabel generik: search, sort, add/edit/delete, modal |

Struktur direktori (dari clone):
```
backend/            (Flask app.py + requirements.txt)
frontend/           (index.html 16KB, app.js 15KB, style.css 3KB)
frontend-react/     (Vite + React + Tailwind + lucide-react)
database_setup.sql
README.md
```

**Tidak ada screenshot/preview** di repository (README tanpa gambar). Tampilan
visual referensi hanya disimpulkan dari kode, bukan tangkapan layar.

---

## 2. Perbandingan `frontend/` (HTML/JS) vs `frontend-react/` (React)

| Aspek | `frontend/` (vanilla) | `frontend-react/` (React) |
|-------|-----------------------|---------------------------|
| Teknologi | HTML + Tailwind CDN + Iconify + JS | Vite + React + Tailwind + lucide-react (butuh `npm install`) |
| Navigasi | top nav horizontal, 18 tab + dropdown "More" | "StaggeredMenu" (dock) + magnify dock |
| Data | tabel CRUD generik + modal + toast | tabel CRUD generik + modal + toast |
| Estetika | admin teal, rapi, berbasis tabel | "Digital Wellness": blob, noise, font cursive, kartu bulat besar, animasi reveal |
| Kepadatan | tabel padat | kartu besar + banyak dekorasi |
| Kesesuaian teknologi | **mirip proyek kita** (vanilla, tanpa build) | butuh build toolchain (tidak diinginkan) |

**Kesimpulan:** dari sisi teknologi, `frontend/` (vanilla) paling dekat dengan
proyek kita (FastAPI + HTML/CSS/JS statis, tanpa npm/build). Namun dari sisi
desain, **keduanya tidak cocok langsung** dengan kebutuhan kita (lihat §5).

---

## 3. Temuan UI Proyek Saat Ini (audit aktual)

- `static/index.html` — login + sidebar (Dashboard, Kendaraan, Backup & Restore) + topbar.
- `static/app.js` — SPA vanilla: dashboard (kartu + daftar aktivitas), daftar
  kendaraan (`.vcard-grid` kartu kompak), detail kendaraan & servis (`.entity-head`
  nama+plat), edit, backup/restore.
- `static/styles.css` — admin biru minimal (`--primary:#2563eb`), `.vcard-grid`
  `repeat(auto-fill, minmax(220px,1fr))`, tabel, responsif ≤768px.
- Sudah memenuhi kebutuhan: dashboard plat+nama, kartu kecil, header nama+plat,
  rincian jasa/part/biaya.

---

## 4. Tabel Perbandingan Desain Referensi vs Proyek Saat Ini

| Aspek | Referensi (vanilla) | Referensi (React) | Proyek saat ini | Catatan |
|-------|---------------------|-------------------|-----------------|---------|
| Layout dashboard | kartu statistik + tabel | hero + kartu statistik besar | 3 kartu + daftar aktivitas kompak | proyek kita lebih padat |
| Navigasi | top nav 18 tab | dock + menu | sidebar 3 menu | proyek kita lebih sederhana |
| Daftar kendaraan | tabel CRUD | tabel CRUD | **kartu kompak grid** | referensi tidak punya konsep kartu |
| Nama + plat sebagai identitas | kolom tabel terpisah | kolom tabel terpisah | header `entity-head` + kartu | sesuai kebutuhan kita |
| Detail kendaraan | tabel Full Data (JOIN) | tabel | header nama+plat + grid | sesuai |
| Tabel jasa & part | tidak ada (katalog terpisah) | tidak ada | tabel jasa + part + ringkasan biaya | referensi tidak relevan |
| Ringkasan biaya | invoice terpisah | invoice | `costSummary` | referensi beda domain |
| Pencarian | client-side filter tabel | client-side filter tabel | server-side `?q=` | kita server-as-truth |
| Responsivitas | top nav + tabel scroll | grid + animasi | sidebar→baris, kartu grid | sesuai |

---

## 5. Bagian Desain yang Direkomendasikan untuk Diadaptasi

**Sedikit / tidak perlu diadaptasi.** Referensi tidak menawarkan pola yang lebih
baik untuk kebutuhan "kartu nama kompak + padat + minimal".

Yang bisa dijadikan acuan kecil (bukan wajib):
1. Pola grid `repeat(auto-fill, minmax(180px,1fr))` untuk kartu — **sudah kita pakai**
   (`minmax(220px,1fr)`).
2. Hover baris `tbody tr:hover { background:#f8fafc }` — sudah ada.
3. Aksen tunggal yang konsisten — sudah ada (biru).

**Tidak disarankan diadaptasi:** estetika "Digital Wellness" (blob, noise, font
cursive, kartu bulat 2rem, animasi reveal) — bertentangan dengan "sederhana,
padat, jelas" dan butuh Tailwind/React (dependensi baru, dilarang).

---

## 6. Rekomendasi Ukuran Kartu, Kepadatan, dan Susunan

- **Grid kartu kendaraan:** `repeat(auto-fill, minmax(200px, 1fr))`, gap 10–12px
  → banyak kartu per baris di monitor.
- **Kartu (kartu nama):** padding 10px 12px; baris 1 = nama (bold) + plat (aksen);
  baris 2 = WA · alamat (12px muted); baris 3 = jenis + tahun (12px muted).
  Tanpa gambar/ikon besar.
- **Dashboard aktivitas:** satu baris = plat (aksen, bold) + nama (13px) di kiri,
  total + tombol "Detail" di kanan.
- **Header detail:** nama (h2) + plat (aksen) sejajar; info lain di grid 2–3 kolom.
- **Detail servis:** jasa & part tabel terpisah; ringkasan biaya di bawah.
- Susunan ini **sudah diterapkan** di H9D-FIX3 — tidak perlu perubahan besar.

---

## 7. Daftar File Proyek yang Kemungkinan Perlu Diubah pada Implementasi

- **Tidak ada perubahan wajib** (kebutuhan sudah terpenuhi H9D-FIX3).
- Jika ingin penyesuaian minor (opsional, butuh persetujuan):
  - `static/styles.css` — fine-tuning `minmax` (220px → 200px) dan font-size kartu.
  - `static/app.js` — (jarang) penyesuaian urutan field kartu.
  - `static/index.html` — bump cache `?v=N` bila CSS berubah.

---

## 8. Hal yang Tidak Dapat Diverifikasi & Alasannya

1. **Tampilan visual nyata kedua frontend** — repository tidak menyertakan
   screenshot/preview; memverifikasi tampilan React membutuhkan `npm install` +
   `npm run dev` (dilarang: memasang dependensi). Kesimpulan visual hanya dari
   pembacaan kode (CSS/JSX).
2. **Alur lengkap `frontend/app.js` dan komponen React lain** (`StaggeredMenu`,
   `MagnificationDock`, `Modal`, `config.js`) tidak dibaca penuh — hanya dipetakan
   dari README dan sebagian file. Tidak berdampak pada kesimpulan (domain CRUD umum).

---

## 9. Konfirmasi

- **Tidak ada kode aplikasi proyek yang diubah** (hanya clone referensi ke `%TEMP%`).
- **Tidak ada database operasional yang diubah** (tanpa operasi tulis).
- **Tidak ada migrasi / `init_db()` / pengujian live**.
- `.env`/`.venv` tidak diubah; tidak ada dependensi baru yang diinstal.

---

**Audit selesai. Berhenti dan menunggu persetujuan sebelum implementasi.**

