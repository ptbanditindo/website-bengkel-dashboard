# Klarifikasi Pengujian Live H2 (50 Skenario)

## Status Bukti Pengujian

Laporan `stage_h2_50_owner_assistant_tests.md` dan `.json` mencatat 50 skenario
dengan status PASS/FAIL. **Pengguna mengklarifikasi bahwa pengujian live
dihentikan setelah sekitar 20 pertanyaan** karena konsumsi API terlalu besar.

Oleh karena itu, status pengujian H2 yang dapat dibuktikan adalah sebagai berikut:

| Kategori | Status |
|----------|--------|
| Skenario yang benar-benar memanggil API DeepSeek | **~20 pertanyaan** (sesuai klarifikasi pengguna) |
| Skenario mana saja yang benar-benar memanggil API | **Tidak dapat ditentukan** dari artefak yang tersedia |
| Status PASS/FAIL per skenario pada laporan H2 | **Belum terverifikasi** (rekonstruksi dari stdout, bukan bukti per-skenario) |
| Jumlah 50 skenario dieksekusi penuh via API nyata | **Tidak diklaim** |

## Alasan Ketidakpastian

1. Runner `tests/live/owner_assistant_50_scenarios.py` awalnya memiliki bug
   `write_reports` (`json.dump` memakai objek `Path`) sehingga **bukti per
   skenario (transcript, tool call, argumen) tidak terpersist**.
2. Status per skenario pada laporan H2 direkonstruksi dari baris status stdout
   run pertama, bukan dari artefak per skenario yang tersimpan.
3. Tidak tersedia log per-skenario yang mencatat kapan/berapa kali API dipanggil
   untuk setiap skenario, sehingga **tidak mungkin memisahkan** skenario yang
   benar-benar memanggil API dari yang hanya berstatus FAIL pada tabel.

## Sikap yang Diambil

- Laporan H2 asli **dipertahankan sebagai catatan historis** dan **tidak ditulis
  ulang** agar tampak berbeda.
- Hasil H2 **tidak dijadikan bukti** dalam audit H3 untuk menyimpulkan bug
  per-skenario. Audit H3 berlandaskan **kode, test deterministik, dan artefak
  yang dapat diverifikasi**, bukan label FAIL pada laporan H2.
- Skenario yang dijalankan secara live **tidak ditebak**. Statusnya dinyatakan
  **belum terverifikasi**.

## Pemisahan Kategori Bukti

1. **Terverifikasi (live API nyata):** hanya smoke test DeepSeek (teks & tool
   call) dari laporan Tahap H, dan klarifikasi "~20 pertanyaan" dari pengguna.
2. **Terverifikasi (deterministik/fixture):** 141 test otomatis di `tests/`
   (in-memory SQLite, tanpa API).
3. **Tercatat di laporan tapi belum terverifikasi:** 50 status PASS/FAIL H2.
4. **Belum dijalankan:** sebagian besar dari 50 skenario H2 (belum dipastikan).
