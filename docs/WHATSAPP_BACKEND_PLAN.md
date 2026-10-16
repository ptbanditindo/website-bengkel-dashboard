# Rancangan Backend WhatsApp CS — Fondasi & Database Terpisah

**Status:** Tahap 1 (audit + rancangan) — belum diimplementasikan
**Tanggal:** 16 Oktober 2026

---

## 1. Hasil Audit (arsitektur yang benar-benar ada)

### 1.1 Database utama
- **Jalur runtime (dari kode, bukan asumsi):** `DATABASE_URL=sqlite:///./data/workshop.db` (terbaca di `.env`; default di `database/session.py::DEFAULT_DATABASE_URL`).
- **Inisialisasi:** `database/session.py::init_db()` -> `run_migrations()` (Alembic `command.upgrade(..., "head")`, non-destructive).
- **Engine:** SQLite, `check_same_thread=False`, `PRAGMA foreign_keys=ON`, `PRAGMA busy_timeout=5000`.
- **Session:** `SessionLocal` (sessionmaker), FastAPI dependency `get_db()`.
- **Migrasi:** Alembic (`migrations/`, `alembic.ini`). 5 versi: `fa7fa27bbb86` (initial), `a1b2c3d4e5f6` (stock_items), `b2c3d4e5f6a7` (stock kode/jumlah + harga_jasa), `c7c0a1b2c3d4` (nama_client optional), `d4e5f6a7b8c9` (warranty fields).
- **Base:** `database/base.py::Base(DeclarativeBase)` dengan naming convention.

### 1.2 Model utama (database/models.py)
| Model | Kolom penting |
|-------|----------------|
| `Vehicle` | `nama_client` (nullable), `nomor_wa` (nullable), `nopol` (unique, non-null), `jenis_mobil`, `tahun_mobil`, `alamat_client` |
| `ServiceRecord` | `vehicle_id`, `waktu_service`, `biaya_jasa`, `total_part`, `total_servis`, `garansi_sampai`, `bergaransi`, `status_klaim` |
| `ServiceJob` | `deskripsi`, `jumlah`, `harga`, `subtotal` |
| `ServicePart` | `nama_part`, `jumlah`, `harga_satuan`, `subtotal`, `stock_item_id` |
| `StockItem` | `kode`, `nama`, `harga_modal`, `harga_jual`, `jumlah` |
| `HargaJasa` | `nama`, `keuntungan` (harga jasa) |

- **Tidak ada entitas pelanggan terpisah.** Identitas pelanggan menempel pada `Vehicle` (`nama_client`, `nomor_wa`). Ini relevan: pencocokan nomor pengirim WhatsApp dilakukan terhadap `Vehicle.nomor_wa`.

### 1.3 Autentikasi
- UI owner: `api/app.py::require_ui_access` — header `Authorization: Bearer <UI_ACCESS_TOKEN>`, constant-time, fail-closed.
- Telegram: `bot/auth.py::require_auth` — whitelist `AUTHORIZED_USER_ID` (multi-user owner).

### 1.4 Telegram & AI
- Bot Telegram polling (`bot/application.py`), handler terstruktur (`bot/handlers.py`) + AI (`bot/ai_handlers.py`).
- Orkestrasi: `ai/orchestrator.py` — loop tool-calling, `PendingAction` (token sekali pakai, per user, TTL).
- Konteks AI: `ai/context.py` — `ConversationStore`, `PendingStore`, `PhotoDraftStore` (semua in-memory, hilang saat restart).
- Tool AI: `ai/tools.py` — registry terpusat; read dieksekusi langsung, mutasi menghasilkan konfirmasi. `record_service_visit` = operasi atomik kendaraan + servis.
- Foto/struk: Gemini (opsional, `GEMINI_API_KEY` kosong saat ini).

### 1.5 Backup / restore
- `services/backup.py`: SQLite Online Backup API; validasi skema (`REQUIRED_TABLES` + `alembic_version`); restore atomik + recovery backup.
- **Risiko penting:** backup saat ini hanya menyentuh `workshop.db`. File DB kedua (`whatsapp_cs.db`) membutuhkan strategi backup sendiri (lihat Bagian 9).

### 1.6 Dependency & pengujian
- Dependency (`requirements.txt`): python-telegram-bot, python-dotenv, openai, SQLAlchemy 2, alembic, fastapi, uvicorn, pytest, pytest-asyncio. Tidak ada dependency baru yang dibutuhkan untuk Tahap 2-4 (SQLite/SQLAlchemy/Alembic sudah ada).
- Pengujian: pytest dengan SQLite in-memory (`tests/conftest.py` fixture `engine`), DB operasional tidak disentuh.

---

## 2. Arsitektur yang diusulkan

```
[ WhatsApp Gateway (Tahap 5, belum ada) ]
        |  webhook masuk (verifikasi)
        v
[ WhatsApp AI CS (DeepSeek, prompt + tool terbatas) ]
        |  tool read-only ke DB utama  |  tool baca/tulis ke DB WhatsApp
        v                              v
[ data/workshop.db (utama, tetap) ]  [ data/whatsapp_cs.db (baru, terpisah) ]
        ^
        |  owner: Telegram + UI (existing)
```

Prinsip:
1. **DB utama tetap satu-satunya sumber data operasional/keuangan** — tidak diubah lokasi/skema/migrasinya.
2. **DB WhatsApp terpisah** (`data/whatsapp_cs.db`) hanya untuk memori CS, kontak, kandidat, rencana kedatangan, tiket owner, dan pengaturan agent.
3. **Referensi silang** disimpan sebagai `linked_vehicle_id` (integer) + snapshot nopol, divalidasi di lapisan aplikasi (tidak ada FK antar-file SQLite).
4. **AI WhatsApp hanya boleh menulis ke DB WhatsApp**; ke DB utama hanya membaca data yang diizinkan (via tool terkontrol, tanpa SQL bebas).
5. **ACC/Tolak dilakukan owner** lewat UI owner (bukan AI WhatsApp); ACC memakai service layer DB utama yang sudah ada, tanpa membuat transaksi servis/stok/keuangan.

## 3. Rancangan Tabel `data/whatsapp_cs.db`

Pakai SQLAlchemy **Base terpisah** (mis. `whatsapp/models.py` + `whatsapp/db.py`), bukan `database.base.Base`, agar migrasi/metadata DB utama tidak terganggu. FK hanya antar-tabel di file yang sama. **Tidak ada** kolom keuangan internal (modal/harga beli/keuntungan/laporan) dan **tidak ada** kolom jumlah stok internal di DB ini.

### 3.1 `wa_contacts` — identitas + memori ringkas per nomor
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| id | INTEGER PK | |
| wa_number | VARCHAR(64) UNIQUE NOT NULL | dari metadata pengirim (bukan teks chat) |
| nama | VARCHAR(255) NULL | dari pelanggan |
| plat | VARCHAR(32) NULL | snapshot input pelanggan |
| jenis_mobil | VARCHAR(255) NULL | |
| tahun_mobil | INTEGER NULL | |
| issue_summary | TEXT NULL | keluhan/kebutuhan |
| context_summary | TEXT NULL | ringkasan percakapan (diperbarui, bukan ditumpuk) |
| registration_status | VARCHAR(32) NOT NULL DEFAULT 'MENUNGGU_REVIEW' | MENUNGGU_REVIEW / DISETUJUI / DITOLAK |
| arrival_status | VARCHAR(32) NULL | KOSONG / MENUNGGU_KEDATANGAN / DIJADWALKAN / DATANG / TIDAK_DATANG |
| linked_vehicle_id | INTEGER NULL | referensi `Vehicle.id` di DB utama (validasi di aplikasi) |
| linked_vehicle_nopol | VARCHAR(32) NULL | snapshot nopol yang ditautkan |
| delay_seconds | INTEGER NOT NULL DEFAULT 60 | delay balasan per nomor |
| last_contact_at | DATETIME NULL | |
| created_at / updated_at | DATETIME | |

Index: unique(`wa_number`), index(`registration_status`), index(`last_contact_at`).

### 3.2 `wa_messages` — riwayat pesan (retensi)
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| id | INTEGER PK | |
| contact_id | INTEGER NOT NULL (FK wa_contacts) | |
| sender | VARCHAR(16) NOT NULL | customer / ai / owner |
| body | TEXT NOT NULL | |
| gateway_message_id | VARCHAR(128) NULL UNIQUE | dedup/idempotensi |
| created_at | DATETIME | |

Retensi: default simpan ringkasan (`context_summary`) permanen; `wa_messages` dapat dihapus setelah N hari (rekomendasi 30 hari, perlu persetujuan owner).

### 3.3 `wa_candidates` — kandidat kendaraan untuk ACC/Tolak owner
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| id | INTEGER PK | |
| contact_id | INTEGER NOT NULL (FK wa_contacts) | |
| nopol | VARCHAR(32) NULL | |
| nama | VARCHAR(255) NULL | |
| jenis_mobil | VARCHAR(255) NULL | |
| tahun_mobil | INTEGER NULL | |
| status | VARCHAR(32) NOT NULL DEFAULT 'MENUNGGU_REVIEW' | MENUNGGU_REVIEW / DISETUJUI / DITOLAK |
| alasan_tolak | TEXT NULL | |
| linked_vehicle_id | INTEGER NULL | diisi saat ACC |
| reviewed_at / reviewed_by | DATETIME / VARCHAR | |
| created_at / updated_at | DATETIME | |

Index: index(`status`), index(`contact_id`).

### 3.4 `wa_arrival_plans` — rencana kedatangan
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| id | INTEGER PK | |
| contact_id | INTEGER NOT NULL (FK wa_contacts) | |
| rencana_hari | VARCHAR(32) NULL | 'hari ini' / 'besok' / 'tanggal' |
| tanggal | DATE NULL | |
| waktu_perkiraan | VARCHAR(32) NULL | |
| status | VARCHAR(32) NOT NULL DEFAULT 'RENCANA' | RENCANA / DATANG / TIDAK_DATANG / BATAL |
| catatan | TEXT NULL | |
| created_at / updated_at | DATETIME | |

Catatan: rencana kedatangan bukan bukti kedatangan aktual; kedatangan aktual ditetapkan owner di UI.

### 3.5 `wa_owner_questions` — antrean pertanyaan untuk owner
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| id | INTEGER PK | |
| contact_id | INTEGER NOT NULL (FK wa_contacts) | |
| wa_number | VARCHAR(64) | snapshot |
| pesan | TEXT | pesan/konteks |
| alasan | TEXT | alasan pengalihan |
| status | VARCHAR(32) NOT NULL DEFAULT 'MENUNGGU' | MENUNGGU / DIJAWAB / DITUTUP |
| jawaban_owner | TEXT NULL | |
| created_at / updated_at | DATETIME | |

Index: index(`status`).

### 3.6 `wa_agent_settings` — pengaturan agent (satu baris)
| Kolom | Tipe | Keterangan |
|-------|------|------------|
| id | INTEGER PK (selalu 1) | |
| nama_bengkel | TEXT | |
| alamat | TEXT | |
| jam_operasional | TEXT | |
| maps_link | TEXT | |
| agent_prompt | TEXT | prompt/pengetahuan agent |
| default_delay_seconds | INTEGER DEFAULT 60 | |
| redirect_enabled | INTEGER 0/1 | pengalihan ke owner |
| updated_at | DATETIME | |

**Penting:** tidak ada kolom kredensial/API key/token di tabel ini. Kredensial tetap di `.env`, tidak pernah dikembalikan lewat API dan tidak pernah dicatat di log.

## 4. Alur Data

### 4.1 Pesan masuk (Tahap 5, gateway belum ada)
```
1. Gateway -> webhook (verifikasi signature + challenge) -> backend.
2. Dedup by gateway_message_id.
3. Muat wa_contacts by wa_number (dari metadata), atau buat baru.
4. Cocokkan wa_number ke Vehicle.nomor_wa di DB utama (bila cocok jelas, 1 pemilik).
5. Bangun konteks AI: memori ringkas + data kendaraan yang diizinkan.
6. AI menjawab via tool terkontrol (hanya baca DB utama yang diizinkan + baca/tulis DB WhatsApp).
7. Simpan pesan + perbarui context_summary (timpa, bukan tumpuk).
8. Terapkan delay per nomor sebelum kirim balasan (lihat 8).
```

### 4.2 Kandidat -> ACC/Tolak (UI owner)
```
1. AI menandai kontak perlu review -> wa_candidates (status MENUNGGU_REVIEW).
2. Owner melihat daftar kandidat di UI (endpoint terautentikasi).
3. ACC: validasi nopol & nomor_wa terhadap DB utama -> dedup -> link vehicle (reuse bila ada) -> set DISETUJUI.
4. Tolak: set DITOLAK + alasan; kontak & ringkasan tetap tersimpan.
```

## 5. Aturan ACC dan Tolak

**ACC bukan transaksi servis.** ACC hanya mengonfirmasi bahwa data kendaraan boleh masuk DB utama.

| Langkah | Aturan |
|---------|--------|
| Validasi | nopol + nomor_wa wajib diperiksa terhadap DB utama sebelum menambah data. |
| Dedup | Jika `nopol` sudah ada -> gunakan Vehicle yang ada (jangan duplikat). Jika `nomor_wa` sudah menempel ke Vehicle lain -> cek kepemilikan. |
| Konflik kepemilikan | Jika nomor/plat tidak cocok jelas -> minta koreksi/tinjauan manual, jangan otomatis menyambung. |
| Efek | ACC hanya menautkan `linked_vehicle_id`; **tidak** membuat ServiceRecord, tidak menetapkan harga final, tidak mengurangi stok, tidak mencatat pendapatan. |
| Audit | Simpan status + `linked_vehicle_id` + `reviewed_at/reviewed_by` di DB WhatsApp. |

**Tolak:**
- Kandidat tidak masuk DB utama; tandai `DITOLAK` + `alasan_tolak` (atau hapus dari antrean aktif — pilih tandai `DITOLAK` agar tetap bisa diaudit).
- Kontak + `context_summary` di DB WhatsApp tetap dipertahankan agar nomor yang sama dikenali lagi.
- Jangan hapus data utama yang sudah terdaftar hanya karena kandidat WhatsApp ditolak.

**Pemisahan status (berbeda, jangan disamakan):**
1. Persetujuan data kendaraan (`registration_status`).
2. Rencana kedatangan (`wa_arrival_plans.status = RENCANA`).
3. Kedatangan aktual (`arrival_status` / plan `DATANG`).
4. Penyelesaian servis (hanya di DB utama via alur servis yang valid).

## 6. Pembatasan Akses AI WhatsApp

Backend wajib membatasi tool, bukan hanya lewat prompt. Tool AI WhatsApp adalah **registry terpisah** dari tool Telegram (`ai/tools.py`).

**Diizinkan (tool terkontrol):**
- Cari kontak by `wa_number` (DB WhatsApp).
- Cocokkan `wa_number` -> `Vehicle` (DB utama, baca `nama_client/nopol/jenis/tahun` milik yang bersangkutan saja).
- Baca riwayat servis kendaraan yang diizinkan (hanya bila kepemilikan cocok jelas).
- Cek ketersediaan barang: jawab `tersedia` / `tidak tersedia` (tanpa jumlah).
- Baca harga jual jasa (`HargaJasa.keuntungan`) dan harga jual part (`StockItem.harga_jual`).
- Simpan memori/keluhan/rencana kedatangan ke DB WhatsApp.
- Buat tiket pertanyaan owner (DB WhatsApp).

**Dilarang:**
- SQL bebas / akses DB mentah.
- Membaca `harga_modal`/harga beli, `keuntungan`, margin, laporan keuangan/pendapatan/transaksi internal.
- Membaca seluruh daftar atau jumlah stok internal.
- Membaca data kendaraan/riwayat servis milik pelanggan lain.
- INSERT/UPDATE/DELETE pada DB utama lewat jalur WhatsApp.

**Enforcement:** setiap tool handler memvalidasi input, memfilter kolom yang dikembalikan, dan menolak operasi terlarang di lapisan service (bukan hanya prompt). Estimasi harga selalu ditandai sebagai perkiraan, bukan harga final.

## 7. Pengalihan kepada Owner

Fondasi: `wa_owner_questions` (lihat 3.5). AI membuat tiket bila: tidak bisa menjawab, data tidak tersedia, ada konflik kepemilikan, atau pelanggan minta manusia.

Isi tiket: `wa_number`, `pesan`, `alasan`, `created_at`, `status` (MENUNGGU/DIJAWAB/DITUTUP), `jawaban_owner`.

**Tidak ada klaim** notifikasi real-time atau balasan manual WhatsApp aktif sampai gateway nyata terpasang.

## 8. Pengaturan Agent dan Delay

- `wa_agent_settings` (3.6): nama bengkel, alamat, jam operasional, link Google Maps, prompt agent, pengalihan owner.
- **Delay per nomor:** `wa_contacts.delay_seconds` (default dari `wa_agent_settings.default_delay_seconds`, contoh 60 detik). Bukan antrean global.
- Pesan beruntun dari nomor yang sama boleh digabung dalam satu jendela tunggu yang dapat dikonfigurasi (debounding).
- Delay bukan cara menghindari batasan platform; gunakan wajar.
- Kredensial tidak disimpan di DB, tidak dikirim ke frontend, tidak tampil di log, tidak dikembalikan lewat API.

## 9. Strategi Backup dan Risiko File DB Kedua

- Backup utama (`services/backup.py`) saat ini hanya menargetkan `workshop.db` (dipanggil dengan `db_url` DB utama).
- `whatsapp_cs.db` harus ikut dicadangkan secara terpisah (metode sama: SQLite Online Backup API), atau backup diperluas agar mencadangkan kedua file.
- **Risiko konsistensi silang:** restore `workshop.db` tidak memulihkan `whatsapp_cs.db`, sehingga `linked_vehicle_id` bisa menunjuk ke id yang berbeda setelah restore. Mitigasi: simpan `linked_vehicle_nopol` sebagai snapshot, dan validasi ulang `linked_vehicle_id` terhadap nopol saat membaca/menautkan; jika tidak cocok, jadikan "perlu tinjauan ulang".
- Backup/restore DB WhatsApp dibuat idempoten dan validatif seperti pola yang ada (cek skema `wa_*` + `alembic_version` bila memakai Alembic kedua).

## 10. Daftar File yang Direncanakan untuk Diubah (Tahap berikutnya)

**Tahap 2 — Database WhatsApp (baru, tidak menyentuh DB utama):**
- `whatsapp/models.py` (baru) — Base terpisah + 6 model di atas.
- `whatsapp/db.py` (baru) — engine `sqlite:///./data/whatsapp_cs.db`, `SessionLocal`, `init_whatsapp_db()` (`create_all`; Alembic kedua opsional).

**Tahap 3 — Backend internal (baru):**
- `whatsapp/repositories/*.py` — akses data per entitas.
- `whatsapp/services/*.py` — contact_service, candidate_service (ACC/Tolak), price_service (read-only DB utama), settings_service, owner_question_service.
- `whatsapp/security.py` — guard akses AI (allowlist kolom + operasi).

**Tahap 4 — Endpoint & UI (menyentuh backend + frontend):**
- `api/app.py` — endpoint owner terautentikasi (daftar kontak/kandidat, detail, ACC/Tolak, ubah status kedatangan, antrean pertanyaan, get/save settings).
- `api/schemas.py` — schema Pydantic baru.
- `static/app.js` / `static/index.html` — hubungkan halaman WhatsApp CS (saat ini DEMO) ke endpoint; hilangkan label DEMO hanya setelah fitur nyata tersedia.
- `services/backup.py` (jika disetujui) — backup kedua DB.

**Tahap 5 — Gateway nyata (belum dikerjakan):**
- Adapter gateway terpisah (mis. `whatsapp/gateway/*.py`) — webhook masuk + kirim balasan; provider dapat diganti tanpa menulis ulang logika bisnis.

**Tidak boleh diubah pada Tahap 2-4:** `bot/` (Telegram), `ai/tools.py` (tool Telegram), `database/` utama, `migrations/` utama, `.env`.

## 11. Rencana Pengujian (belum dijalankan)

- Unit repository/service DB WhatsApp memakai SQLite in-memory terpisah (pola `tests/conftest.py`).
- ACC: dedup nopol (reuse), konflik nomor/plat, data wajib kurang, dan "ACC tidak membuat ServiceRecord/stok/keuangan".
- Tolak: kandidat ditandai DITOLAK, kontak & ringkasan tetap ada.
- Akses AI: tool read-only tidak mengembalikan `harga_modal`/`keuntungan`/jumlah stok/data pelanggan lain; operasi tulis ke DB utama ditolak.
- Pengalihan owner: pembuatan tiket + transisi status.
- Delay: nilai per nomor independen, default 60 detik.
- Backup DB WhatsApp: create + validate + restore idempoten.
- **Tidak ada test yang menyentuh `data/workshop.db` operasional.**

## 12. Risiko & Pertanyaan Terbuka

| Risiko | Dampak | Mitigasi |
|--------|--------|----------|
| DB kedua terpisah bisa tidak sinkron dengan DB utama | `linked_vehicle_id` menunjuk data lama | Simpan snapshot nopol + validasi ulang saat dipakai |
| Backup DB kedua belum tercakup | Data CS hilang saat restore | Perluas backup (butuh persetujuan) |
| AI membaca data sensitif | Kebocoran keuangan/data pelanggan | Registry tool terpisah + filter kolom + validasi kepemilikan |
| ACC keliru menulis DB utama | Data operasional tercemar | ACC memakai service DB utama yang sudah ada, tanpa transaksi servis |
| Inisialisasi DB kedua tanpa migrasi | Skema sulit berevolusi | `create_all` untuk v1; Alembic kedua bila perlu (persetujuan) |

**Pertanyaan untuk owner:**
1. Pakai `create_all` (sederhana) atau Alembic kedua untuk DB WhatsApp?
2. Kebijakan retensi `wa_messages` (rekomendasi 30 hari)?
3. Default delay per nomor (contoh 60 detik) dan jendela penggabungan pesan?
4. Apakah backup perlu diperluas ke dua DB sekarang atau nanti?

## 13. Status Tes

- **Belum ada tes yang dijalankan pada tahap ini** (audit & rancangan saja, sesuai batasan tugas).
- Rencana pengujian di Bagian 11 adalah **rencana**, bukan hasil nyata; akan dijalankan pada Tahap 2-4.
- Tidak ada perubahan pada `data/workshop.db`, Telegram, frontend, `.env`, atau dependency selama Tahap 1.

---

## Kesimpulan
Tahap 1 selesai: jalur DB utama teridentifikasi dari kode runtime (`data/workshop.db`), arsitektur terpetakan, dan rancangan `whatsapp_cs.db` disusun tanpa mencampur data keuangan/stok internal. Implementasi (Tahap 2-4) menunggu persetujuan owner.


---

## Status Implementasi (update WA-02 s.d. WA-12)

| Rancangan (Bagian) | Status |
|--------------------|--------|
| 3. Rancangan 6 tabel | TERIMPLEMENTASI (whatsapp/models.py + db.py, create_all) |
| 4. Alur data | TERIMPLEMENTASI (service layer + agent + gateway mock) |
| 5. ACC/Tolak | TERIMPLEMENTASI (CandidateService.approve/reject + endpoint) |
| 6. Pembatasan akses AI | TERIMPLEMENTASI (whatsapp/agent.py tool terkontrol) |
| 7. Pengalihan owner | TERIMPLEMENTASI (wa_owner_questions + endpoint) |
| 8. Pengaturan & delay | TERIMPLEMENTASI (wa_agent_settings + PerNumberQueue) |
| 9. Backup DB kedua | TERIMPLEMENTASI (whatsapp/backup.py) |
| 10. Daftar file (Tahap 2-4) | TERIMPLEMENTASI (lihat laporan implementasi) |
| 11. Rencana pengujian | TERJALAN (29 tes baru, 332 total passed) |
| Gateway nyata (Tahap 5) | BELUM (menunggu provider/gateway dipilih pemilik) |
