# Website Bengkel Dashboard (AI Bengkel)

Asisten AI untuk mengelola bengkel mobil: pelanggan, kendaraan, riwayat servis, suku cadang, biaya jasa, garansi, dan layanan WhatsApp — lengkap dengan dashboard admin lokal (web).

- **Dashboard web lokal** — panel admin (login token) untuk mengelola kendaraan, riwayat servis, garansi, stok, harga jasa, laporan, serta backup/restore.
- **Telegram bot** — asisten AI (DeepSeek) memahami bahasa Indonesia sehari-hari dan memanggil tool bisnis; perintah manual tetap tersedia.
- **WhatsApp CS** — customer service AI via WhatsApp (Baileys gateway) dengan takeover owner, kandidat kendaraan, rencana kedatangan, dan pertanyaan owner.
- **Perhitungan di kode** — subtotal, total part, biaya jasa, total servis, dan profit dihitung aplikasi (Decimal), bukan AI.
- **Garansi** — setiap servis punya `garansi_sampai` dan status klaim (Belum claim / Sudah claim).
- **Gambar** — Gemini (opsional) mengekstrak nota/foto; hasil harus dikonfirmasi sebelum disimpan.
- **Backup & restore** — database SQLite dapat di-backup/di-restore dari dashboard.

## Tech Stack

- Python 3.10+
- python-telegram-bot
- DeepSeek API dan Gemini API (OpenAI-compatible)
- SQLAlchemy + Alembic + SQLite
- FastAPI + uvicorn (API & dashboard)
- Node.js + Baileys (gateway WhatsApp)
- Docker & Docker Compose

## Struktur

    ai/            provider AI, tool, orkestrasi percakapan
    api/           REST API + dashboard lokal (FastAPI)
    bot/           handler, otorisasi, interaksi Telegram
    whatsapp/      layanan & model WhatsApp CS
    Knightbot-MD/   bot WhatsApp Baileys + bridge HTTP
    config/        penyimpanan kredensial integrasi (server-side)
    database/      model, engine, session
    repositories/  akses data
    services/      logika bisnis
    static/        UI dashboard (HTML/JS/CSS)
    migrations/    migrasi skema Alembic
    tests/         pengujian otomatis
    data/          database & sesi lokal (di-gitignore)
    main.py        entry point bot Telegram
    run_api.py     entry point API + dashboard

## Instalasi lokal

1. Clone repository.
2. Buat virtualenv dan install dependensi:

       python -m venv venv
       venv\Scripts\activate
       pip install -r requirements.txt

3. Salin `.env.example` ke `.env`:

       copy .env.example .env

4. Isi `.env` (lihat Konfigurasi di bawah).
5. (Opsional) Untuk WhatsApp CS, install dan jalankan Knightbot-MD:

       cd Knightbot-MD
       npm install
       npm start

## Konfigurasi (.env)

| Variabel | Wajib | Deskripsi |
|----------|-------|-----------|
| TELEGRAM_TOKEN | Ya | Token bot dari @BotFather |
| AUTHORIZED_USER_ID | Ya | ID user Telegram yang diizinkan (pisahkan koma) |
| DATABASE_URL | Ya | sqlite:///./data/workshop.db (default) |
| UI_ACCESS_TOKEN | Ya (dashboard) | Token akses dashboard/API (bearer) |
| DEEPSEEK_API_KEY | Tidak | API key DeepSeek (percakapan AI) |
| DEEPSEEK_MODEL | Tidak | default deepseek-flash |
| GEMINI_API_KEY | Tidak | API key Gemini (gambar) |
| GEMINI_MODEL | Tidak | default gemini-3.8-flash |
| APP_HOST | Tidak | default 127.0.0.1 |
| APP_PORT | Tidak | default 8000 |
| BACKUP_DIR | Tidak | default data/backups |

Perilaku saat API key kosong:
- `DEEPSEEK_API_KEY` kosong -> AI percakapan memberi tahu belum dikonfigurasi; perintah manual (/daftar, /servis, dll.) tetap berfungsi.
- `GEMINI_API_KEY` kosong -> pemrosesan foto memberi tahu fitur belum tersedia; percakapan teks tetap berfungsi.

Jangan menaruh API key di source code atau commit `.env`. Kredensial integrasi (Telegram/DeepSeek/Gemini) juga bisa dikelola dari dashboard (menu Integrasi) dan disimpan di `data/integration_settings.json` (di-gitignore, tidak pernah disajikan sebagai file statis).

## Database

Alembic adalah mekanisme resmi perubahan skema. Saat aplikasi berjalan, `init_db()` menjalankan migrasi Alembic (`alembic upgrade head`) secara otomatis dan non-destruktif (tidak drop/reset).

    alembic upgrade head
    alembic revision --autogenerate -m "pesan"

## Menjalankan bot Telegram

    python main.py

## Menjalankan API + dashboard

    python run_api.py
    # atau: uvicorn api.app:app --host 127.0.0.1 --port 8000

Buka `http://127.0.0.1:8000/ui` lalu login dengan `UI_ACCESS_TOKEN`.

Dashboard menyediakan menu: Dashboard, Kendaraan, Riwayat Servis, Garansi, Stok, Harga Jasa, WhatsApp CS, Integrasi, dan Backup & Restore. Seluruh data dilindungi endpoint `/api/*` ber-token.

## Menjalankan tes

    python -m pytest tests/ -v

Semua tes memakai mock/database sementara; tidak memanggil API berbayar.

## Docker

    docker compose up -d --build

- Migrasi (`alembic upgrade head`) dijalankan saat container start (non-destruktif).
- Database tersimpan di volume `bot-data` (/app/data).
- Tidak ada reset/penghapusan database.

## Perintah bot

| Perintah | Deskripsi |
|----------|-----------|
| /start, /help | Menu dan bantuan |
| /daftar | Daftarkan kendaraan baru |
| /servis | Catat riwayat servis |
| /cari plat | Cari kendaraan |
| /riwayat plat | Riwayat servis |
| /garansi plat | Status garansi |
| /klaim plat | Ubah status klaim garansi |
| /hapus plat | Hapus kendaraan |

Selain perintah, cukup ketik kalimat biasa (mis. catat servis mobil B 1234 ABC ganti radiator 850 ribu) dan AI akan memahami lalu meminta konfirmasi sebelum menyimpan.

## Catatan

- Pengujian terhadap API DeepSeek/Gemini nyata belum dilakukan (semua tes memakai mock). Tes integrasi nyata memerlukan persetujuan terpisah.
- Konfirmasi AI bersifat sementara (in-memory) dan batal saat restart; token terikat pada user dan kedaluwarsa otomatis.

## License

MIT