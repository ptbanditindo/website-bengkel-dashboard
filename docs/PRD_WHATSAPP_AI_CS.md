# PRD — Modul WhatsApp AI Customer Service (AI CS) Bengkel

**Status:** Draf untuk review owner — belum disetujui, belum diimplementasikan
**Proyek target:** `Telegram-Finance-Bot` (AI Bengkel)
**Tanggal:** 15 Oktober 2026

---

## 1. Ringkasan Produk dan Tujuan

### 1.1 Ringkasan

Modul **WhatsApp AI Customer Service** menambahkan jalur komunikasi baru antara **pelanggan** dan bengkel melalui WhatsApp. Sebuah AI Customer Service (AI CS) akan menerima pesan WhatsApp masuk, memahami konteks setiap nomor secara terpisah, mengumpulkan informasi kendaraan/keluhan secara bertahap, dan menghasilkan **calon pelanggan** yang ditampilkan di **UI owner** untuk ditinjau.

Telegram **tetap tidak berubah** dan tetap menjadi jalur komunikasi **owner ↔ sistem bengkel**. WhatsApp menjadi jalur **pelanggan ↔ AI CS bengkel**. Keduanya membaca/menulis database operasional yang sama, tetapi dengan peran dan hak yang berbeda.

### 1.2 Tujuan

1. Pelanggan dapat bertanya/melaporkan keluhan lewat WhatsApp tanpa didaftarkan manual oleh owner.
2. AI CS mengumpulkan informasi minimal yang berguna (nomor, nama, plat, jenis/tahun kendaraan, keluhan) tanpa memaksa pelanggan.
3. AI CS menyimpan **memori ringkas per nomor WhatsApp** — bukan transkrip penuh — sehingga nomor yang sama yang menghubungi berhari/minggu kemudian tetap dikenali.
4. **Owner tetap memegang kendali penuh**: hanya owner yang dapat menyetujui pendaftaran ke database utama, menolak, mengoreksi data, atau mengubah status kedatangan.
5. Tidak ada data calon pelanggan yang otomatis masuk database operasional utama; tidak ada riwayat servis/stok/keuntungan yang berubah hanya karena seseorang mengirim pesan atau memberikan plat.

### 1.3 Prinsip desain utama

- **Pemisahan logis**: memori percakapan WhatsApp ≠ database utama pelanggan/kendaraan ≠ riwayat servis/stok/garansi.
- **Hemat penyimpanan**: utamakan ringkasan terstruktur, bukan transkrip penuh.
- **Tanpa asumsi**: jika informasi tidak diketahui, AI tidak boleh mengarang/menganggap benar.
- **Idempotensi & konsistensi**: pesan duplikat atau pemrosesan bersamaan tidak boleh menghasilkan data ganda.
- **Tidak mengganggu sistem lama**: Telegram, UI, dan database operasional tetap berfungsi.

---

## 2. Kondisi Arsitektur Saat Ini (Hasil Audit)

Hasil audit read-only terhadap `Telegram-Finance-Bot`.

### 2.1 Arsitektur umum

| Lapisan | Komponen | Keterangan |
|---------|----------|------------|
| Web/API | `api/app.py` (FastAPI), `run_api.py`, `main.py` | API lokal + penyajian UI `static/`. Default bind `127.0.0.1`. |
| Bot | `bot/application.py`, `bot/handlers.py`, `bot/ai_handlers.py`, `bot/auth.py` | Bot Telegram (polling, bukan webhook) untuk owner. |
| AI | `ai/providers.py`, `ai/orchestrator.py`, `ai/tools.py`, `ai/context.py` | Orkestrasi AI + function calling. |
| DB | `database/models.py`, `database/base.py`, `database/session.py`, `migrations/` (Alembic) | SQLite + ORM + migration. |
| Service | `services/*` | Logika bisnis, validasi, pricing, reporting, backup. |
| Repo | `repositories/*` | Akses data terstruktur. |
| UI | `static/index.html`, `static/app.js`, `static/styles.css` | SPA owner (fetch API + Bearer token). |

### 2.2 Database (SQLite + Alembic)

- Engine SQLite `sqlite:///./data/workshop.db`, dikonfigurasi via `DATABASE_URL`; dapat pindah ke PostgreSQL dengan mengganti URL.
- Migration dikelola Alembic (`migrations/env.py`, `migrations/versions/*`).

Model utama (hasil audit):

| Model | Peran | Relasi penting |
|-------|-------|----------------|
| `Vehicle` | Kendaraan (plat, merk, model, tahun, warna) | 1 → N `ServiceRecord` |
| `ServiceRecord` | Satu kunjungan/servis kendaraan | N → 1 `Vehicle`; 1 → N `ServiceJob`; 1 → N `ServicePart` |
| `ServiceJob` | Pekerjaan jasa dalam satu servis | ref `HargaJasa` |
| `ServicePart` | Spare part yang dipakai | ref `StockItem` |
| `StockItem` | Stok barang (kode, nama, harga, stok) | — |
| `HargaJasa` | Katalog harga jasa | — |

- **Belum ada entitas "pelanggan (customer)" independen** — identitas pelanggan saat ini menempel pada data servis / kolom nama client yang opsional (ada migration `c7c0a1b2c3d4_make_nama_client_optional`). PRD ini **tidak** menimpa struktur servis yang ada; identitas pelanggan WhatsApp dirancang terpisah.
- **Belum ada** tabel untuk kontak WhatsApp, memori percakapan, atau antrian approval. Semua itu baru dan harus dirancang.

### 2.3 Autentikasi & keamanan yang sudah ada

- **UI owner**: endpoint membutuhkan header `Authorization: Bearer <UI_ACCESS_TOKEN>` (`require_ui_access`).
- **Telegram**: `require_auth` memvalidasi `AUTHORIZED_USER_ID` (daftar ID dipisah koma) → mendukung multi-user owner.
- Default bind `127.0.0.1` → UI owner diakses lokal. Belum ada login per-user (satu bearer token bersama).

### 2.4 Frontend owner yang sudah ada

- SPA statis `static/index.html` + `app.js` + `styles.css`.
- Pola UI: **sidebar navigasi** (Dashboard, Kendaraan, Riwayat Servis, Stok, Harga Jasa, Garansi) + **topbar** + **panel** + **toolbar** (search/filter/chips) + **card/table** + **badge status** + **modal** + **banner hasil aksi**.
- Navigasi client-side di `app.js` (render per section, tanpa router library).
- Dashboard menampilkan kartu statistik + kartu keuangan + grafik (data dari `/api/profit/history` dst.).

### 2.5 Integrasi Telegram & alur AI yang sudah ada

- Bot Telegram menggunakan **polling**, bukan webhook.
- `ai_message_handler` → `orchestrator.handle_message`; tool baca dieksekusi langsung, tool mutasi (tambah servis, kurangi stok, dst.) meminta **konfirmasi inline button** sebelum dieksekusi (`PendingStore`).
- `ai/context.py` menyimpan riwayat percakapan **di memori** (bounded, ±20 pesan) per pengguna (`ConversationStore`) — **tidak dipersist ke DB**, hilang saat restart. Ada `PhotoDraftStore` untuk draft foto/struk.
- Foto/struk diproses Gemini bila dikonfigurasi.

### 2.6 Konfigurasi provider AI yang sudah ada

| Variabel | Peran |
|----------|-------|
| `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` (default `deepseek-flash`) | Model utama percakapan + function calling |
| `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-3.8-flash`) | Opsional: pemrosesan gambar/struk |
| `TELEGRAM_TOKEN`, `AUTHORIZED_USER_ID` | Bot Telegram + whitelist owner |
| `DATABASE_URL` | SQLite lokal |
| `APP_HOST`, `APP_PORT` | Bind API/UI lokal |
| `UI_ACCESS_TOKEN` | Bearer token UI owner |
| `BACKUP_DIR` | Direktori backup SQLite |

- **Belum ada** konfigurasi WhatsApp/gateway/provider apa pun (tidak ada `WHATSAPP_*`, `META_*`, dst.).
- Provider AI sudah diabstraksi (`ai/providers.py`), sehingga modul WhatsApp dapat menggunakan ulang komponen AI yang sama.

### 2.7 Pola validasi, transaksi, logging, pengujian

- Validasi terpusat di `services/validation.py`; service memakai transaksi DB (`commit`/`rollback`) dan melempar exception terdefinisi (`services/exceptions.py`).
- Logging terstandar; backup SQLite tersedia (`services/backup.py`).
- Pengujian `pytest` (`tests/*`) memakai DB test terpisah via `conftest.py`.

---

## 3. Ruang Lingkup dan Yang Tidak Termasuk

### 3.1 Termasuk (dalam cakupan PRD)

- Jalur masuk pesan WhatsApp → AI CS → memori ringkas per nomor.
- Antrian & status calon pelanggan (menunggu review / disetujui / ditolak) + status kedatangan.
- UI owner untuk dashboard, daftar antrian, dan detail kontak + aksi ACC/Tolak/koreksi/ubah status.
- Persetujuan owner → pendaftaran pelanggan/kendaraan ke database utama (dengan dedup & validasi).
- Integrasi gateway WhatsApp + reuse provider AI.
- Keamanan webhook & endpoint API owner.

### 3.2 Tidak termasuk (di luar cakupan)

- Mengubah alur Telegram yang ada.
- Otomatisasi servis/stok/keuntungan dari percakapan WhatsApp (tanpa persetujuan owner & alur operasional valid).
- Blast/broadcast marketing WhatsApp, notifikasi massal, atau chatbot penjualan e-commerce.
- Mengganti database operasional, reset data, atau menghapus data lama.
- Redesign/refactor frontend keseluruhan.
- Multi-tenant bengkel (PRD mengasumsikan satu bengkel/satu kelompok owner).

---

## 4. Persona dan Hak Akses

| Persona | Hak | Batasan |
|---------|-----|---------|
| **Pelanggan (via WhatsApp)** | Mengirim pesan; menerima balasan AI CS; memberikan nama/plat/keluhan; bertanya perkiraan biaya; diingat oleh memori ringkas. | Tidak bisa mengubah data operasional; tidak bisa membaca data pelanggan lain; tidak bisa menyetujui apa pun. |
| **Owner (via UI)** | Melihat dashboard & antrian; meninjau/mengoreksi data calon pelanggan; ACC/Tolak; mengubah status kedatangan; melihat ringkasan memori. | Akses UI tetap via bearer token (`UI_ACCESS_TOKEN`). |
| **AI CS** | Membaca memori ringkas per nomor; mengumpulkan info; menjawab pertanyaan (termasuk perkiraan biaya dari katalog yang sudah ada); menandai kontak sebagai "perlu review". | Tidak menulis ke database utama tanpa persetujuan owner; tidak mengarang data; tidak membocorkan data pelanggan lain. |
| **Sistem backend** | Memproses webhook, memanggil AI, menyimpan memori ringkas, menjalankan aksi owner secara idempoten. | Mengikuti aturan bisnis; mencatat audit trail. |

---

## 5. Alur Utama WhatsApp (Pesan Pertama → Persetujuan)

```
1. Pelanggan mengirim pesan WhatsApp (teks/gambar) ke nomor bisnis bengkel.
2. Gateway WhatsApp → webhook → backend (verifikasi tanda tangan + idempotensi).
3. Backend memuat (atau membuat) memori ringkas untuk nomor pengirim (dari metadata).
4. AI CS membaca memori + pesan → menghasilkan balasan + update memori terstruktur.
5. Jika informasi cukup untuk "perlu review", kontak ditandai status = MENUNGGU_REVIEW.
6. Balasan dikirim ke pelanggan (dengan penanganan kegagalan/retry).
7. Owner membuka UI → dashboard/antrian → detail kontak.
8. Owner meninjau/mengoreksi data → ACC atau Tolak.
   - ACC: validasi wajib + dedup nomor/plat → buat/perbarui pelanggan & kendaraan di DB utama.
   - Tolak: simpan status ditolak, pertahankan memori, tidak sentuh DB utama.
9. Owner dapat memperbarui status kedatangan (MENUNGGU_KEDATANGAN → DIJADWALKAN → DATANG / TIDAK_DATANG).
```

**Aturan penting dalam alur:**
- Nomor WhatsApp diambil dari **metadata pengirim** gateway, bukan dari teks yang diketik pelanggan.
- Kontak baru **tidak otomatis** masuk DB utama hanya karena mengirim pesan / memberi plat / minta estimasi.
- AI CS **tidak** membuat riwayat servis, tidak mengubah stok, tidak menghitung keuntungan.
- Jika data belum lengkap, AI CS menanyakan satu per satu secara natural (nama → plat → jenis/tahun → keluhan), tanpa memaksa.

---

## 6. Alur Pelanggan Lama Kembali

```
1. Nomor yang sama menghubungi lagi (beberapa jam/hari/minggu kemudian).
2. Backend memuat memori ringkas yang tersimpan untuk nomor itu.
3. AI CS mengonfirmasi konteks lama dari ringkasan (mis. "Masih soal AC kurang dingin ya?").
4. Jika pelanggan memberi info baru, AI CS memperbarui ringkasan secara terstruktur (bukan menumpuk).
5. Jika kontak sebelumnya ditolak, status penolakan tetap tersimpan agar tidak tampil sebagai
   "kontak baru belum pernah ditinjau"; owner tetap bisa meninjau ulang/menyetujui lagi.
```

**Aturan:**
- Memori nomor A **tidak boleh** tercampur dengan nomor B.
- AI **tidak boleh** mengungkap riwayat kendaraan/servis milik pelanggan lain berdasarkan pengetahuan plat.
- Jika memori tidak lengkap/kontradiktif/basi, AI menanyakan konfirmasi, bukan mengarang (lihat §7).

---

## 7. Aturan Memori Ringkas per Nomor

### 7.1 Prinsip

Memori ringkas adalah **ringkasan terstruktur**, bukan transkrip. Ia hanya menyimpan hal yang berguna untuk percakapan berikutnya.

### 7.2 Struktur memori (logis)

| Field | Keterangan |
|-------|------------|
| `wa_number` | Nomor WhatsApp (dari metadata pengirim) — identitas utama |
| `customer_name` | Nama pelanggan, jika diketahui |
| `vehicle_plate` | Plat nomor, jika diketahui |
| `vehicle_type` / `vehicle_year` | Jenis & tahun kendaraan, jika diketahui |
| `issue_summary` | Keluhan / kebutuhan perbaikan (ringkas) |
| `context_summary` | Ringkasan konteks percakapan terakhir |
| `last_contact_at` | Waktu kontak terakhir |
| `registration_status` | Status pendaftaran (lihat §8) |
| `arrival_status` | Status kedatangan (lihat §8) |
| `pending_review_at` | Kapan ditandai perlu review |
| `updated_at` | Waktu pembaruan memori |

### 7.3 Aturan penyimpanan

- **Nomor dari metadata**: nomor pengirim harus berasal dari metadata platform WhatsApp, bukan teks yang diketik.
- **Tanpa transkrip permanen**: pesan basa-basi, respons berulang, dan info tak relevan tidak disimpan.
- **Update, bukan menumpuk**: ringkasan lama **diganti** ketika ada info baru (mis. plat berubah → timpa field `vehicle_plate`), bukan ditambahkan sebagai baris baru.
- **Tidak mengarang**: field yang tidak diketahui dibiarkan kosong (NULL), bukan diisi tebakan.
- **Versi ringkasan**: pertahankan satu ringkasan terkini per field; bila perlu simpan `previous_*` ringkas untuk resolusi kontradiksi (opsional, dijelaskan §7.4).

### 7.4 Menghadapi memori tidak lengkap / kontradiktif / basi

| Kasus | Perilaku AI CS |
|-------|----------------|
| Tidak lengkap | Tanya field yang kurang satu per satu; jangan tebak. |
| Kontradiktif (mis. plat berbeda dari memori) | Konfirmasi ke pelanggan ("Kemarin platnya X, sekarang Y — yang benar yang mana?"); jangan langsung timpa tanpa konfirmasi. |
| Basi / tidak relevan (lama sekali) | Konfirmasi apakah masih membahas topik lama; jika tidak, mulai ringkasan topik baru tanpa menghapus identitas (nomor/nama/plat). |
| Nomor sama, pemilik kendaraan tampak berbeda | Jangan otomatis gabung; minta konfirmasi & catat sebagai kontradiksi untuk review owner. |

---

## 8. Aturan Persetujuan, Penolakan, dan Kedatangan

### 8.1 Status pendaftaran (`registration_status`)

| Status | Arti |
|--------|------|
| `MENUNGGU_REVIEW` | Calon pelanggan siap ditinjau owner (belum diputuskan). |
| `DISETUJUI` | Disetujui masuk database utama. |
| `DITOLAK` | Ditolak masuk database utama. |

### 8.2 Status kedatangan (`arrival_status`) — terpisah dari pendaftaran

| Status | Arti |
|--------|------|
| `KOSONG` / belum diatur | Belum relevan (belum disetujui). |
| `MENUNGGU_KEDATANGAN` | Disetujui, menunggu pelanggan datang. |
| `DIJADWALKAN` | Sudah ada janji kedatangan (jika proses dijadwalkan didukung). |
| `DATANG` | Pelanggan sudah datang. |
| `TIDAK_DATANG` | Pelanggan tidak datang. |
| `SERVIS_SELESAI` | Hanya jika pekerjaan servis benar-benar selesai (opsional, mengikuti alur operasional). |

### 8.3 Transisi status yang sah

**Pendaftaran:**
```
MENUNGGU_REVIEW → DISETUJUI
MENUNGGU_REVIEW → DITOLAK
DITOLAK        → MENUNGGU_REVIEW  (owner meninjau ulang)
DITOLAK        → DISETUJUI        (owner berubah keputusan)
DISETUJUI      → (tetap; tidak kembali ke MENUNGGU_REVIEW otomatis)
```

**Kedatangan (hanya berarti setelah DISETUJUI):**
```
KOSONG → MENUNGGU_KEDATANGAN → DIJADWALKAN → DATANG
                              ↘ TIDAK_DATANG
DATANG / TIDAK_DATANG → (jika servis selesai) → SERVIS_SELESAI
```

**Catatan penting:**
- Penolakan pendaftaran **tidak** berarti pelanggan tidak datang; penolakan hanya soal masuk/tidaknya ke DB utama.
- Kedatangan **tidak** otomatis berarti servis sudah dilakukan.
- `SERVIS_SELESAI` hanya boleh di-set melalui alur operasional servis yang valid (bukan oleh AI CS/WhatsApp).

### 8.4 Saat owner menyetujui (ACC)

1. Validasi data wajib (minimal: nomor WhatsApp; nama & plat jika tersedia disarankan).
2. Cek duplikasi:
   - Nomor WhatsApp sudah terhubung ke pelanggan? → gunakan kembali, jangan duplikat.
   - Plat kendaraan sudah ada di `Vehicle`? → gunakan kembali kendaraan itu.
3. Buat/perbarui entitas pelanggan & kendaraan di DB utama hanya jika perlu.
4. **Tidak** membuat riwayat servis otomatis.
5. **Tidak** mengubah stok atau perhitungan keuntungan.

### 8.5 Saat owner menolak (Tolak)

- **Tidak** memasukkan calon pelanggan ke entitas operasional utama.
- **Pertahankan** memori ringkas (AI tetap mengenali nomor itu).
- **Simpan** status `DITOLAK` agar UI tidak terus menampilkannya sebagai "kontak baru belum pernah ditinjau".
- Owner tetap dapat meninjau ulang / menyetujui lagi di kemudian hari.

### 8.6 Nomor / plat yang sudah terdaftar (termasuk tidak cocok)

- **Nomor WhatsApp sudah terhubung ke pelanggan lain**: jangan buat pelanggan baru; tautkan kontak ke pelanggan yang ada; jika kontradiktif, tandai untuk review owner.
- **Plat sudah terdaftar ke kendaraan lain**: gunakan kembali `Vehicle` yang ada; jangan duplikat.
- **Nomor WhatsApp & pemilik kendaraan tidak cocok** (nomor milik A, plat milik B): jangan otomatis menyambung; tampilkan sebagai peringatan di detail kontak dan minta keputusan owner.

---

## 9. Wireframe Tekstual (Mengikuti Pola UI Saat Ini)

Menggunakan ulang pola UI yang sudah ada (sidebar + topbar + panel + toolbar + card/table + badge + modal). **Tidak** mengganti desain keseluruhan.

### 9.1 Navigasi

Sidebar saat ini: Dashboard, Kendaraan, Riwayat Servis, Stok, Harga Jasa, Garansi.

**Tambah satu item**: **"WhatsApp CS"** — ditempatkan setelah "Dashboard" (atau sebagai grup terpisah). Tidak menghapus item yang ada.

### 9.2 Dashboard WhatsApp CS

```
┌────────────────────────────────────────────────────────────┐
│ Topbar: "WhatsApp CS"            [tombol aksi sesuai konteks] │
├────────────────────────────────────────────────────────────┤
│ [Menunggu Review: 5] [Disetujui: 12] [Ditolak: 3] [Menunggu/Dijadwalkan: 4] │   ← kartu statistik (data nyata dari API)
├────────────────────────────────────────────────────────────┤
│ Panel "Kontak Terbaru"                                       │
│  toolbar: [cari: nomor/nama/plat] [filter status ▾] [rentang tanggal ▾] │
│  daftar kontak (ringkas, mudah dipindai):                     │
│   ┌────────────────────────────────────────────────────────┐│
│   │ 0812xxxx  |  B 1234 XYZ  |  "AC kurang dingin"  | 2 jam lalu | [Menunggu] [Menunggu Kedatangan] │
│   │ 0856xxxx  |  (belum ada)  |  "Ganti oli + cek rem" | 1 hari lalu | [Ditolak] [—] │
│   └────────────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────┘
```

### 9.3 Detail kontak (saat satu kontak dibuka)

```
┌────────────────────────────────────────────────────────────┐
│ Panel "Detail Kontak"           [Kembali]                    │
│  Identitas: Nama (jika ada), No. WhatsApp (metadata)        │
│  Kendaraan: Plat | Jenis | Tahun (jika diketahui)           │
│  Keluhan: ringkasan keluhan                                  │
│  Memori ringkas: ringkasan konteks percakapan terakhir       │
│  Waktu kontak terakhir: ...                                  │
│  Status pendaftaran: [badge]   Status kedatangan: [badge]    │
│  Data belum lengkap: [nama?] [plat?] [jenis/tahun?]          │
├────────────────────────────────────────────────────────────┤
│ Aksi: [ACC] [Tolak] [Koreksi Data] [Ubah Status Kedatangan]  │
│  (sebelum ACC: tampilkan ringkasan data yang akan dibuat/     │
│   diperbarui, minta konfirmasi akhir)                         │
└────────────────────────────────────────────────────────────┘
```

Catatan: transkrip lengkap **bukan** kebutuhan wajib; tampilkan ringkasan yang hemat penyimpanan.

### 9.4 Hasil aksi

- Banner/toast hasil aksi (pola yang sudah ada) setelah ACC/Tolak/koreksi/ubah status.
- Jika aksi berpotensi membuat data operasional → tampilkan dialog konfirmasi berisi **daftar entitas yang akan dibuat/diperbarui** sebelum eksekusi final.
- Cegah pengiriman berulang: tombol aksi **disabled** selama request berjalan (pola idempoten + `idempotency_key`).

---

## 10. Spesifikasi Backend dan Penyimpanan

### 10.1 Entitas logis (rancangan, bukan perintah membuat tabel sekarang)

| Entitas logis | Tanggung jawab | Relasi |
|---------------|----------------|--------|
| `WaContact` | Identitas kontak WhatsApp (nomor, status pendaftaran, status kedatangan, waktu kontak terakhir). | 1 → 1 `WaMemory`; N → 0..1 `Customer` (setelah ACC). |
| `WaMemory` | Memori ringkas terstruktur per nomor (nama, plat, jenis/tahun, ringkasan keluhan, ringkasan konteks). | 1 → 1 `WaContact`. |
| `WaReviewRequest` (opsional) | Permintaan review calon pelanggan (snapshot data saat perlu review + status). | N → 1 `WaContact`. |
| `WaEventLog` (opsional) | Log aksi penting (pesan masuk, ACC, Tolak, ubah status) untuk audit — **bukan transkrip**. | N → 1 `WaContact`. |
| `Customer` (BARU) | Pelanggan yang disetujui di DB utama (jika audit menyimpulkan perlu entitas pelanggan terpisah). | 1 → N `Vehicle`. |
| `Vehicle` (ADA) | Kendaraan operasional utama. | 1 → N `ServiceRecord`. |
| `ServiceRecord`, `ServiceJob`, `ServicePart`, `StockItem`, `HargaJasa` (ADA) | Data operasional yang TIDAK boleh disentuh oleh alur WhatsApp tanpa alur valid. | — |

**Reuse vs baru (hasil audit):**
- `Vehicle`, `ServiceRecord`, `ServiceJob`, `ServicePart`, `StockItem`, `HargaJasa` **dipakai ulang apa adanya**.
- Saat ini **tidak ada entitas pelanggan independen**; PRD mengusulkan entitas `Customer` baru sebagai jembatan antara `WaContact` dan `Vehicle`, tanpa menimpa struktur servis.
- `WaContact`, `WaMemory`, dan status/antrian adalah **baru** (tidak ada di skema saat ini).

### 10.2 Konteks terpisah per nomor

- Kunci utama memori = **nomor WhatsApp dari metadata** (unik, case/format dinormalisasi, mis. `62812...`).
- Setiap percakapan AI CS selalu memuat/merujuk `WaMemory` milik nomor pengirim saja. Tidak ada query lintas-nomor untuk konteks.
- Prompt AI menyertakan memori **hanya** untuk nomor aktif; tidak menyertakan memori/histori pelanggan lain.

### 10.3 Memperbarui memori tanpa duplikasi

- Satu baris `WaMemory` per `WaContact` (1:1). Update memori = **UPDATE** field terkait, bukan INSERT baru.
- AI diminta menghasilkan **patch terstruktur** (field + nilai baru), lalu backend menerapkan patch hanya untuk field yang diizinkan.
- Ringkasan lama ditimpa oleh ringkasan baru yang sudah menggabungkan info lama + baru (single source of truth).

### 10.4 Pesan WhatsApp yang sama terkirim ulang (idempotensi)

- Setiap event webhook membawa `message_id` unik dari gateway.
- Backend menyimpan/mengecek `message_id` (dedup) — jika sudah diproses, abaikan tanpa memanggil AI ulang.
- Aksi owner memakai `idempotency_key` dari frontend agar double-click tidak membuat data ganda.

### 10.5 Konsistensi saat dua pesan diproses hampir bersamaan

- Serialisasi pemrosesan per `wa_number` (mis. lock/queue per nomor) agar dua pesan dari nomor yang sama tidak saling menimpa memori.
- Transaksi DB atomik untuk update memori + status; gunakan pola commit/rollback yang sudah ada.
- Untuk SQLite, pertimbangkan write serialization + retry pendek saat `database is locked`.

### 10.6 Mencegah pendaftaran ganda

- Saat ACC: transaksi tunggal yang (1) cek nomor WhatsApp, (2) cek plat, (3) create/reuse `Customer`+`Vehicle`, (4) tautkan `WaContact` → `Customer`.
- Unique constraint pada nomor WhatsApp (di `WaContact`) dan pada plat (di `Vehicle`) sebagai penjaga terakhir.
- Jika entitas sudah ada → reuse; tidak pernah membuat duplikat.

### 10.7 Keamanan webhook & API owner

- **Webhook WhatsApp**: verifikasi tanda tangan/secret gateway (mis. header signature + `WEBHOOK_VERIFY_TOKEN` untuk challenge), HTTPS, validasi struktur payload, dan hanya proses `message_id` yang valid.
- **API owner**: endpoint UI/approval memakai bearer token yang sama dengan sistem saat ini (`UI_ACCESS_TOKEN`) atau mekanisme auth UI yang disepakati.
- Webhook **tidak** boleh memanggil endpoint owner yang protected; pisahkan router webhook (publik, terverifikasi) dari router owner (auth).

### 10.8 Penanganan pesan / respons AI yang gagal

- Jika gateway gagal kirim balasan → retry dengan backoff; catat status gagal di log; jangan kirim ganda tanpa dedup.
- Jika provider AI gagal/timeout → kirim fallback sopan ("CS sedang sibuk, mohon tunggu / hubungi bengkel"), simpan pesan sebagai "belum terproses" agar bisa dilanjutkan.
- Jangan pernah expose detail error internal/stacktrace ke pelanggan.

### 10.9 Backup, migrasi, dan pemulihan

- Ikut mekanisme backup SQLite yang sudah ada (`services/backup.py`, `BACKUP_DIR`).
- Migration baru ditambahkan **bertahap dan additive** via Alembic; tidak mengubah/menimpa tabel lama.
- Pemulihan: data operasional lama dipulihkan seperti biasa; `WaContact`/`WaMemory` ikut dalam file DB yang sama.

### 10.10 Kebijakan retensi & penghapusan (rekomendasi, perlu persetujuan owner)

- **Default**: simpan ringkasan terstruktur saja (hemat), **tanpa** penghapusan otomatis.
- Transkrip penuh (jika suatu saat diaktifkan) sebaiknya bersifat **sementara** (retensi pendek, mis. 30 hari) atau tidak disimpan sama sekali.
- Dampak penghapusan: kehilangan konteks keluhan lama → AI mungkin bertanya ulang. Oleh karena itu **tidak disarankan** menghapus `WaMemory` otomatis; kebijakan retensi harus **disetujui owner** sebelum diimplementasikan.
- Data pelanggan berhak meminta penghapusan data pribadi sesuai regulasi (mis. UU PDP) — sediakan jalur manual owner.

---

## 11. Spesifikasi Integrasi WhatsApp dan AI

### 11.1 Perbandingan kebutuhan vs kondisi saat ini

| Kebutuhan | Kondisi saat ini | Keputusan yang perlu dibuat |
|-----------|------------------|------------------------------|
| Provider/gateway WhatsApp | **Belum ada** (tidak ada konfigurasi WhatsApp) | Pilih provider (mis. WhatsApp Business Cloud API / Twilio / 360dialog / WATI). |
| Webhook pesan masuk | **Belum ada** (Telegram pakai polling) | Perlu endpoint webhook publik + HTTPS (beda dari bot Telegram polling). |
| Pengiriman balasan AI | **Belum ada** untuk WhatsApp | Perlu integrasi API kirim pesan + penanganan fail/retry. |
| Verifikasi webhook | **Belum ada** | Perlu secret/token verifikasi (challenge + signature). |
| Penyimpanan nomor pengirim & id pesan | **Belum ada** | Perlu `WaContact.wa_number` + dedup `message_id`. |
| Provider AI | **Ada** (`DEEPSEEK_*`, `GEMINI_*`) | Gunakan ulang; tentukan model utama untuk CS (default DeepSeek). |
| Kunci/secret | Ada `.env` (`UI_ACCESS_TOKEN`, dsb.) | Tambah var baru saat implementasi (bukan di tahap PRD). |

### 11.2 Keputusan yang masih perlu dibuat (pertanyaan terbuka untuk owner)

1. Provider/gateway WhatsApp mana yang dipakai (termasuk nomor bisnis & biaya).
2. Apakah webhook dihosting di jaringan lokal yang sama (perlu tunnel/HTTPS) atau di VPS publik.
3. Model AI utama untuk CS (DeepSeek default vs Gemini) dan apakah Gemini tetap khusus gambar/struk.
4. Bahasa & gaya balasan CS (formal/santai, bahasa Indonesia).
5. Apakah AI CS boleh memberikan **estimasi harga** langsung (read-only dari katalog `HargaJasa`/`StockItem`) — direkomendasikan ya, read-only.

### 11.3 Rancangan integrasi (rekomendasi)

- **Provider AI**: reuse `ai/providers.py` + `ai/orchestrator.py`; tambah "persona CS WhatsApp" terpisah (system prompt) dengan tool read-only (cari harga jasa, cari stok) — **tanpa** tool mutasi.
- **Gateway**: webhook inbound → verifikasi → normalisasi `wa_number` → load memori → panggil AI → simpan patch memori → kirim balasan.
- **Kunci**: semua secret di `.env` (tidak di-hardcode); konfigurasi baru ditambahkan **hanya saat implementasi**, tidak sekarang.
- **Batas waktu respons**: target balasan < beberapa detik; jika AI timeout, gunakan fallback sopan (lihat §10.8).
- **Perilaku aman bila AI tidak tersedia**: CS tetap menjawab fallback, pesan dicatat sebagai "belum terproses" agar bisa dilanjutkan saat AI pulih; tidak ada data operasional yang diubah.

---

## 12. Validasi, Keamanan, Konsistensi, dan Penanganan Kegagalan (ringkasan)

| Aspek | Aturan |
|-------|--------|
| Validasi input | Nomor dari metadata; plat/nama/keluhan divalidasi format sebelum disimpan/di-ACC. |
| Validasi ACC | Data wajib terpenuhi; cek dedup nomor & plat sebelum create. |
| Keamanan webhook | Verifikasi signature + challenge token; HTTPS; hanya `message_id` valid. |
| Keamanan API owner | Bearer token (`UI_ACCESS_TOKEN`); pisahkan router webhook vs owner. |
| Privasi | AI hanya menerima memori nomor aktif; tidak membocorkan data pelanggan lain. |
| Konsistensi | Transaksi atomik; serialisasi per nomor; unique constraint nomor & plat. |
| Idempotensi | Dedup `message_id` (webhook) + `idempotency_key` (aksi owner). |
| Kegagalan gateway | Retry + backoff; jangan kirim ganda. |
| Kegagalan AI | Fallback sopan + tandai "belum terproses"; tidak ubah data operasional. |
| Audit | `WaEventLog` mencatat aksi penting (bukan transkrip penuh). |

---

## 13. Kriteria Penerimaan (dapat diuji)

1. Pesan WhatsApp dari nomor baru membuat `WaContact`+`WaMemory` dengan `wa_number` dari metadata, bukan dari teks.
2. Nomor yang sama tidak membuat memori ganda; update menimpa ringkasan lama.
3. Data calon pelanggan **tidak** muncul di DB utama sebelum owner ACC.
4. Owner dapat melihat antrian (menunggu/disetujui/ditolak + kedatangan) dengan data nyata dari backend.
5. ACC membuat/menghubungkan `Customer`+`Vehicle` tanpa duplikat (nomor & plat unik); tidak membuat `ServiceRecord`/mengubah stok.
6. Tolak menyimpan status `DITOLAK`, mempertahankan memori, dan kontak tidak tampil sebagai "baru belum ditinjau".
7. Nomor yang sama kembali seminggu kemudian dikenali dari memori (AI konfirmasi keluhan lama).
8. Status kedatangan terpisah dari status pendaftaran dan hanya relevan setelah disetujui.
9. Pesan duplikat (`message_id` sama) diproses sekali saja.
10. Dua pesan hampir bersamaan dari nomor sama tidak merusak memori.
11. Webhook tidak terverifikasi ditolak; endpoint owner tanpa token ditolak (401).
12. Telegram & UI yang ada tetap berfungsi; database operasional lama tidak berubah/reset.
13. AI/gateway gagal → fallback sopan, tanpa mengubah data operasional.

---

## 14. Risiko, Dependensi, dan Pertanyaan Terbuka

### 14.1 Risiko

| Risiko | Dampak | Mitigasi |
|--------|--------|----------|
| Belum ada gateway WhatsApp | Modul tidak bisa berjalan tanpa provider. | Pilih provider lebih dulu; desain gateway-agnostik. |
| Webhook butuh HTTPS publik | Infrastruktur lokal (bind `127.0.0.1`) tidak cukup. | VPS publik / tunnel (ngrok/cloudflared) — perlu keputusan. |
| AI "mengarang" data pelanggan | Salah registrasi/kebocoran. | Prompt tegas + tool read-only + validasi owner + dedup. |
| Kebocoran data antar nomor | Pelanggan lain melihat data. | Memori per nomor terisolasi; jangan query lintas nomor. |
| Double-click / pesan duplikat | Data ganda. | Idempotensi (`message_id`, `idempotency_key`) + unique constraint. |
| SQLite write contention | `database is locked` saat pesan serentak. | Serialisasi per nomor + retry; pertimbangkan migrasi ke PostgreSQL saat skala naik. |
| Ketergantungan pada konteks in-memory Telegram | (terpisah) riwayat Telegram hilang saat restart. | Modul WhatsApp menggunakan memori **persisten** (DB), bukan in-memory. |

### 14.2 Dependensi

- Provider/gateway WhatsApp (keputusan eksternal).
- Kunci API AI yang sudah ada (`DEEPSEEK_*`, `GEMINI_*`) tetap valid.
- Infrastruktur hosting webhook (HTTPS publik).
- Keputusan owner atas kebijakan retensi data.

### 14.3 Pertanyaan terbuka (untuk owner)

1. Provider WhatsApp & nomor bisnis yang dipakai.
2. Hosting webhook (lokal+tunnel vs VPS publik).
3. Bolehkah AI CS memberikan estimasi harga read-only?
4. Gaya bahasa & tone CS.
5. Kebijakan retensi/penghapusan data percakapan.
6. Perlu entitas `Customer` baru, atau cukup menyimpan referensi pelanggan di data servis yang ada?

---

## 15. Tahapan Implementasi yang Direkomendasikan (setelah PRD disetujui)

1. **Skema & migration additive**: tambah `WaContact`, `WaMemory` (+ `WaReviewRequest`/`WaEventLog` opsional) via Alembic; tanpa menyentuh tabel lama.
2. **Repository & service**: logika load/save memori, dedup `message_id`, serialisasi per nomor.
3. **Persona AI CS**: system prompt + tool read-only (cari harga/stok) reuse `ai/*`; tanpa tool mutasi.
4. **Integrasi gateway WhatsApp**: webhook + verifikasi + kirim balasan (di belakang keputusan provider).
5. **API owner**: endpoint daftar antrian, detail, ACC/Tolak, koreksi, ubah status (auth bearer).
6. **UI owner**: tambah item navigasi "WhatsApp CS", dashboard, daftar, detail, modal konfirmasi ACC (pola UI lama).
7. **Pengujian**: unit + integrasi untuk memori, dedup, ACC dedup, status transisi, keamanan webhook/API.
8. **UAT + rollback plan**: backup DB sebelum deploy; pantau log; pastikan Telegram/UI lama tidak terdampak.

---

## 16. Skenario Uji Contoh

### S1. Kontak baru bertanya keluhan kendaraan
- **Diberikan**: nomor `62812...` (baru) mengirim "Mobil saya AC-nya kurang dingin".
- **Diharapkan**: backend membuat `WaContact`+`WaMemory` dengan `wa_number` dari metadata; AI CS membalas bertanya nama/plat; belum ada data di DB utama; status `MENUNGGU_REVIEW` hanya setelah info cukup.

### S2. Owner menolak pendaftaran
- **Diberikan**: kontak S1 sudah `MENUNGGU_REVIEW`; owner klik **Tolak**.
- **Diharapkan**: status → `DITOLAK`; tidak ada `Customer`/`Vehicle`/`ServiceRecord` baru; `WaMemory` tetap ada; kontak tampil di daftar "Ditolak", bukan "baru belum ditinjau".

### S3. Nomor yang sama kembali seminggu kemudian
- **Diberikan**: seminggu kemudian `62812...` mengirim "Halo, masih soal AC itu".
- **Diharapkan**: AI CS memuat memori dan mengonfirmasi konteks lama ("Masih soal AC kurang dingin ya?"); tidak membuat memori baru; tidak menumpuk ringkasan.

### S4. Owner kemudian menyetujui pendaftaran
- **Diberikan**: owner membuka detail kontak S1 dan klik **ACC**.
- **Diharapkan**: muncul konfirmasi "akan membuat Pelanggan + Kendaraan (plat X)"; setelah konfirmasi, `Customer`+`Vehicle` dibuat **tanpa duplikat**; tidak ada `ServiceRecord`/perubahan stok; status → `DISETUJUI`.

### S5. Nomor WhatsApp atau plat sudah terdaftar
- **Diberikan**: nomor lain mengirim dengan plat `B 1234 XYZ` yang sudah ada di `Vehicle`.
- **Diharapkan**: sistem mendeteksi duplikat; saat ACC, reuse `Vehicle` yang ada (tidak duplikat); jika nomor WhatsApp milik pelanggan A tapi plat milik B → tampilkan peringatan dan minta keputusan owner (tidak otomatis menyambung).

### S6. Pelanggan datang tetapi belum melakukan servis
- **Diberikan**: kontak berstatus `DISETUJUI` + `MENUNGGU_KEDATANGAN`; owner set `DATANG`.
- **Diharapkan**: status kedatangan berubah jadi `DATANG`; **tidak** ada `ServiceRecord` yang dibuat; stok/keuntungan tidak berubah; `SERVIS_SELESAI` hanya bisa di-set melalui alur servis valid.

### S7. Pesan duplikat atau pemrosesan bersamaan
- **Diberikan**: webhook mengirim ulang `message_id` yang sama; atau dua pesan dari nomor sama tiba hampir bersamaan.
- **Diharapkan**: `message_id` sama diproses sekali saja; dua pesan bersamaan diproses serial per nomor sehingga `WaMemory` konsisten (tidak saling timpa).

### S8. AI atau gateway WhatsApp gagal
- **Diberikan**: provider AI timeout, atau gateway gagal mengirim balasan.
- **Diharapkan**: pelanggan menerima fallback sopan; pesan ditandai "belum terproses"; tidak ada perubahan data operasional; setelah pulih, pesan dapat dilanjutkan.

---

## Catatan Penutup

Dokumen ini hanya **PRD** (rancangan produk). Pada tahap ini **tidak ada** perubahan kode, migration, database, `.env`, dependensi, workflow Telegram, maupun frontend. Implementasi dimulai hanya setelah owner meninjau dan menyetujui dokumen ini serta menjawab pertanyaan terbuka pada §14.3.


---

