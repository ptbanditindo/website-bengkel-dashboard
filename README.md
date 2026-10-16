# AI Bengkel Telegram Bot

Asisten AI untuk mengelola data bengkel mobil lewat Telegram: pelanggan, kendaraan, riwayat servis, suku cadang, biaya servis, dan garansi.

- **Percakapan AI** - DeepSeek memahami bahasa Indonesia sehari-hari dan memanggil tool bisnis.
- **Database lokal** - SQLite via SQLAlchemy (siap beralih ke PostgreSQL lewat DATABASE_URL).
- **Perhitungan di kode** - subtotal, total part, biaya jasa, dan total servis dihitung aplikasi (Decimal), bukan AI.
- **Garansi** - setiap servis punya garansi_sampai dan status_klaim (Belum claim / Sudah claim).
- **Gambar** - Gemini (opsional) mengekstrak nota/foto; hasil harus dikonfirmasi sebelum disimpan.
- **Fondasi API localhost** - FastAPI untuk UI visual mendatang.

## Tech Stack

- Python 3.10+
- python-telegram-bot
- DeepSeek API (OpenAI-compatible) dan Gemini API (OpenAI-compatible)
- SQLAlchemy + Alembic + SQLite
- FastAPI + uvicorn (fondasi API)
- Docker & Docker Compose

## Struktur

    ai/            provider AI, tool, orkestrasi percakapan
    api/           fondasi API localhost (FastAPI)
    bot/           handler, otorisasi, interaksi Telegram
    database/      model, engine, session, migrasi
    repositories/  akses data
    services/      logika bisnis
    tests/         pengujian otomatis
    data/          database lokal (di-gitignore)
    main.py        entry point bot
    run_api.py     entry point API

## Instalasi lokal

1. Clone repository.
2. Buat virtualenv dan install dependensi:

       python -m venv venv
       venv\Scripts\activate
       pip install -r requirements.txt

3. Salin .env.example ke .env:

       copy .env.example .env

4. Isi .env (lihat Konfigurasi di bawah).

## Konfigurasi (.env)

| Variabel | Wajib | Deskripsi |
|----------|-------|-----------|
| TELEGRAM_TOKEN | Ya | Token bot dari @BotFather |
| AUTHORIZED_USER_ID | Ya | ID user Telegram yang diizinkan (pisahkan koma) |
| DATABASE_URL | Ya | sqlite:///./data/workshop.db (default) |
| DEEPSEEK_API_KEY | Tidak | API key DeepSeek (percakapan AI) |
| DEEPSEEK_MODEL | Tidak | default deepseek-flash |
| GEMINI_API_KEY | Tidak | API key Gemini (gambar) |
| GEMINI_MODEL | Tidak | default gemini-3.8-flash |
| APP_HOST | Tidak | default 127.0.0.1 |
| APP_PORT | Tidak | default 8000 |

Perilaku saat API key kosong:
- DEEPSEEK_API_KEY kosong -> AI percakapan memberi tahu belum dikonfigurasi; perintah manual (/daftar, /servis, dll.) tetap berfungsi.
- GEMINI_API_KEY kosong -> pemrosesan foto memberi tahu fitur belum tersedia; percakapan teks tetap berfungsi.

Jangan menaruh API key di source code atau commit .env.

## Database

Alembic adalah mekanisme resmi perubahan skema. Saat aplikasi berjalan, `init_db()` menjalankan migrasi Alembic (`alembic upgrade head`) secara otomatis dan non-destruktif (tidak drop/reset).

Migrasi skema lewat Alembic:

    alembic upgrade head
    alembic revision --autogenerate -m "pesan"

Migrasi bersifat non-destruktif (tidak drop/reset).

## Menjalankan bot

    python main.py

## Menjalankan API localhost (fondasi UI)

    python run_api.py
    # atau: uvicorn api.app:app --host 127.0.0.1 --port 8000

API saat ini hanya health check (GET /health). Endpoint data pelanggan belum dibuat karena autentikasi API belum diimplementasikan.

## Menjalankan tes

    python -m pytest tests/ -v

Semua tes memakai mock/database sementara; tidak memanggil API berbayar.

## Docker

    docker compose up -d --build

- Migrasi (alembic upgrade head) dijalankan saat container start (non-destruktif).
- Database tersimpan di volume bot-data (/app/data).
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
