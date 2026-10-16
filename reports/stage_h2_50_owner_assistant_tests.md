# Laporan Live Test 50 Skenario — AI Asisten Pemilik Bengkel

## Ringkasan
- **Provider nyata yang diuji:** DeepSeek `deepseek-flash` (Gemini SKIPPED — key kosong).
- **Smoke test:** teks ✅ (2.34s), tool calling ✅ (`search_vehicle_by_plate`, 0.71s).
- **Hasil 50 skenario:** **PASS 19 | FAIL 31 | SKIPPED 0**.
- **Database uji:** SQLite terisolasi per skenario (temp dir). Database operasional `data/workshop.db` TIDAK disentuh.

## Hasil per Skenario

| ID | Kel | Status | Nama |
|----|-----|--------|------|
| H001 | A | FAIL | Daftar kendaraan lengkap |
| H002 | A | FAIL | Kendaraan info tidak lengkap |
| H003 | A | FAIL | Servis total saja |
| H004 | A | FAIL | Servis beberapa part |
| H005 | A | FAIL | Jasa dan part terpisah |
| H006 | A | FAIL | Servis kendaraan terdaftar |
| H007 | A | FAIL | Beberapa pekerjaan |
| H008 | A | FAIL | Tanggal servis eksplisit |
| H009 | A | FAIL | Garansi tersedia |
| H010 | A | FAIL | Daftar + servis gabungan |
| H011 | B | FAIL | 3 kendaraan satu sesi |
| H012 | B | FAIL | Servis 2 kendaraan |
| H013 | B | FAIL | Info pelanggan dulu |
| H014 | B | FAIL | Part bertahap |
| H015 | B | FAIL | Koreksi harga |
| H016 | B | FAIL | Lengkapi setelah klarifikasi |
| H017 | B | FAIL | Dua servis terpisah |
| H018 | B | FAIL | Beberapa instruksi |
| H019 | C | PASS | Cari by plat |
| H020 | C | PASS | Cari by nama |
| H021 | C | PASS | Semua kendaraan pelanggan |
| H022 | C | PASS | Riwayat servis |
| H023 | C | PASS | Servis terbaru |
| H024 | C | FAIL | Cari by jenis+tahun |
| H025 | C | FAIL | Cari servis by pekerjaan |
| H026 | C | PASS | Part + harga |
| H027 | C | PASS | Status garansi |
| H028 | C | PASS | Data tidak ditemukan |
| H029 | D | FAIL | Jumlah kendaraan unik |
| H030 | D | PASS | Servis rentang tanggal |
| H031 | D | FAIL | Total nilai servis |
| H032 | D | PASS | Pelanggan paling sering |
| H033 | D | FAIL | Pekerjaan paling sering |
| H034 | D | FAIL | Kendaraan dalam garansi |
| H035 | D | PASS | Ringkasan kegiatan |
| H036 | E | PASS | Batal (tidak jadi) |
| H037 | E | PASS | Tolak konfirmasi |
| H038 | E | FAIL | Setujui konfirmasi |
| H039 | E | FAIL | Koreksi sebelum konfirmasi |
| H040 | E | FAIL | Koreksi data tersimpan |
| H041 | E | PASS | Batal setelah sebagian info |
| H042 | E | PASS | Hapus ber-riwayat ditolak |
| H043 | F | FAIL | Tanya data terakhir |
| H044 | F | FAIL | Pindah topik |
| H045 | F | FAIL | Dua kendaraan (klarifikasi) |
| H046 | F | PASS | Info bertentangan |
| H047 | F | PASS | Angka tak bisa ditentukan |
| H048 | F | PASS | Error provider (kontrol) |
| H049 | F | FAIL | Pesan berulang |
| H050 | F | PASS | Isolasi pending antar sesi |

## Temuan Utama (Bug)

### Bug H2-1 (P1): Pemetaan argumen tool untuk pencatatan data sangat tidak akurat
- **Bukti:** seluruh Kelompok A (H001–H010) dan Kelompok B (H011–H018) **FAIL**. Skema paling dasar pun ("daftarkan Budi plat B 1234 XYZ, Avanza 2021") tidak menghasilkan kendaraan dengan field benar.
- **Analisis:** mekanisme tool calling & konfirmasi berfungsi (Kelompok C query lulus; H037 pending action terbentuk), tetapi model `deepseek-flash` tidak andal memetakan bahasa Indonesia ke argumen tool `create_vehicle`/`add_service_record` (field jenis/tahun/harga/part sering salah/terlewat).
- **Lokasi:** `ai/tools.py` (skema tool & `SYSTEM_PROMPT`), perilaku model.

### Bug H2-2 (P1): Permintaan gabungan kendaraan+servis tidak selesai (H010)
- Konfirmasi Bug H1 Tahap H — model hanya memanggil `create_vehicle`, tidak `add_service_record`.

### Bug H2-3 (P2): Fitur laporan/analisis belum ada tool-nya (Kelompok D)
- H029/H031/H033/H034 gagal karena **tidak ada tool laporan** (count, sum, agregasi). AI tidak bisa menghitung dari DB tanpa tool khusus.
- Perhitungan harus dipindah ke tool/service (Python), bukan model.

### Bug H2-4 (P2): `write_reports` JSON memakai objek `Path` sebagai file
- `AttributeError: 'WindowsPath' object has no attribute 'write'` — sudah diperbaiki di runner (pakai `open()`). Ini bug test-runner, bukan aplikasi.

## Keterbatasan
- Gemini tidak diuji (key kosong).
- Telegram end-to-end nyata tidak dilakukan (butuh interaksi manual pemilik).
- Detail transcript/tool call per skenario tidak terpersist (bug write_reports pada run pertama); status per skenario tercatat lengkap.

## Kesimpulan
**Status akhir: FAIL** (fitur inti AI — pencatatan data via percakapan — tidak andal; 62% skenario gagal).
Kemampuan baca data (query) bekerja baik, tetapi kemampuan tulis data (pencatatan kendaraan/servis) belum layak operasional tanpa perbaikan prompt/skema tool.

## Konfirmasi
- Database operasional `data/workshop.db` TIDAK berubah (semua mutasi di DB temp terisolasi).
- Tidak ada API key/token yang tercetak. Tidak ada pesan Telegram nyata.
