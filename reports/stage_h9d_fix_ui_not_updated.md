# Laporan H9D-FIX — Audit Penyebab UI Tidak Berubah

## Status: **PASS**

Penyebab teridentifikasi dengan bukti: **server sudah menyajikan kode baru, tetapi
browser memakai cache file JS/CSS lama.** Perbaikan cache-busting diterapkan pada
`index.html`.

---

## 1. Penyebab yang Ditemukan & Bukti

Audit sistematis (bukan asumsi):

| Pemeriksaan | Hasil | Bukti |
|-------------|-------|-------|
| Direktori proyek | benar | satu salinan tiap file di `static/` |
| Duplikasi file | tidak ada | `app.js` (29616 B), `styles.css` (7541 B), `index.html` (1518 B) — masing-masing 1 file |
| Perubahan H9D ada di disk | ya | `node --check` OK; konten berisi `data-nav`, `vehicleCards`, `hasParts`, `card-view` |
| HTML memuat file benar | ya | `/ui` berisi `/static/app.js` dan `/static/styles.css` |
| Referensi lama/cache-busting | **tidak ada cache-busting** (ini akar masalah) | `<script src="/static/app.js">` tanpa versi |
| Routing server | benar | `/ui` dan `/static/*` tersaji; proses `run_api.py` (PID 19640) memegang port 8000 |
| Isi yang disajikan server | **identik dengan disk** | SHA256 `app.js` disk == served (`a686e7de…`); `styles.css` sama |
| Cache-Control server | `None` (tidak ada cache server) | header respons |
| Error JavaScript | tidak ada | `node --check` lulus |
| Selector CSS vs HTML | sesuai | `.card-view`/`.mcard`/`.clickable` didefinisikan & dirender |

**Kesimpulan terverifikasi:** tidak ada masalah di sisi server (file, routing,
proses, atau cache server). UI lama muncul karena **browser menyimpan salinan
`/static/app.js` dan `/static/styles.css` versi lama** dan tidak memuat ulang.

---

## 2. Perbaikan yang Dilakukan

Menambah **cache-busting query string** (`?v=2`) agar browser menganggap URL
sebagai baru dan memuat ulang file:

| File | Perubahan |
|------|-----------|
| `static/index.html` | `<link href="/static/styles.css?v=2">` dan `<script src="/static/app.js?v=2">` |

Verifikasi:
- `/ui` kini memuat `styles.css?v=2` dan `app.js?v=2`.
- `GET /static/app.js?v=2` → 200 (29616 B, konten baru).
- `GET /static/styles.css?v=2` → 200 (7541 B, konten baru).

---

## 3. File yang Diperiksa & Diubah

- **Diperiksa (read-only):** `static/app.js`, `static/styles.css`, `static/index.html`,
  `api/app.py` (routing), proses yang melayani port 8000, hash disk vs served.
- **Diubah:** hanya `static/index.html` (cache-busting `?v=2`).

Tidak ada perubahan pada `app.js`, `styles.css`, backend, API, model, skema.

---

## 4. Hasil Verifikasi & Pengujian

```
node --check static/app.js                         -> JS syntax OK
python -m pytest tests/test_ui.py -q               -> 5 passed
hash(disk app.js) == hash(served app.js)           -> True
hash(disk styles.css) == hash(served styles.css)   -> True
/static/app.js?v=2 -> 200 (29616 B); /static/styles.css?v=2 -> 200 (7541 B)
```

- Verifikasi visual browser **belum dilakukan** (tidak ada browser otomatis).

---

## 5. Langkah Manual yang Masih Diperlukan

1. Di browser, buka ulang **http://127.0.0.1:8000/ui** (refresh normal cukup karena
   URL `?v=2` baru; bila masih lama, tekan **Ctrl+F5**).
2. Perubahan H9D akan terlihat: tombol "Detail" di dashboard, kartu seluler di
   Daftar Kendaraan, nama pekerjaan di ringkasan, dan "Belum tersedia" di detail servis.

---

## 6. Git Status

- `static/` berstatus untracked (pre-existing); perubahan hanya pada
  `static/index.html`.

---

## 7. Konfirmasi

- **Backend/API tidak berubah.**
- **Database operasional tidak berubah** (tidak disentuh; tidak ada operasi tulis).
- **Migrasi tidak dijalankan** (tanpa `init_db()`/Alembic).
- `.env`/`.venv` tidak diubah; tanpa dependensi baru; tanpa pengujian live.

---

## 8. Risiko / Masalah Belum Terselesaikan

- Cache-busting `?v=2` bersifat manual: setiap perubahan `app.js`/`styles.css`
  berikutnya perlu menaikkan versi (mis. `?v=3`) agar pengguna lain yang sudah
  membuka UI tidak memakai cache lama. Alternatif jangka panjang: tambahkan
  header `Cache-Control: no-cache` untuk `static/` (perubahan kecil di `api/app.py`)
  — diusulkan, belum diterapkan.

---

**Setelah laporan ini, saya berhenti dan menunggu persetujuan Anda.**
