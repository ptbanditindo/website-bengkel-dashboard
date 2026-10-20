# Website Bengkel Dashboard (AI Bengkel)

Asisten AI untuk mengelola bengkel mobil: pelanggan, kendaraan, riwayat servis, suku cadang, biaya jasa, garansi, dan layanan WhatsApp — lengkap dengan dashboard admin lokal (web).

- **Dashboard web lokal** — panel admin (login token) untuk mengelola kendaraan, riwayat servis, garansi, stok, harga jasa, laporan, serta backup/restore.
- **Telegram bot** — asisten AI (DeepSeek/OpenRouter) memahami bahasa Indonesia sehari-hari dan memanggil tool bisnis; perintah manual tetap tersedia.
- **WhatsApp CS** — customer service AI via WhatsApp (Baileys gateway) dengan takeover owner, kandidat kendaraan, rencana kedatangan, dan pertanyaan owner.
- **Perhitungan di kode** — subtotal, total part, biaya jasa, total servis, dan profit dihitung aplikasi (Decimal), bukan AI.
- **Garansi** — setiap servis punya `garansi_sampai` dan status klaim (Belum claim / Sudah claim).
- **Gambar** — OpenRouter vision mengekstrak nota/foto; hasil harus dikonfirmasi sebelum disimpan.
- **Backup & restore** — database SQLite dapat di-backup/di-restore dari dashboard.

## Tech Stack

- Python 3.10+
- python-telegram-bot
- DeepSeek API dan OpenRouter API (OpenAI-compatible)
- SQLAlchemy + Alembic + SQLite
- FastAPI + uvicorn (API & dashboard)
- Node.js + Baileys (gateway WhatsApp)
- Docker & Docker Compose

## Struktur

    ai/            provider AI bersama (DeepSeek + OpenRouter) + error
    api/           REST API + dashboard lokal (FastAPI)
    bot/           handler, otorisasi, interaksi Telegram
    bot/ai/        orkestrasi, tool, dan context AI Telegram
    whatsapp/      layanan & model WhatsApp CS
    gateway/       bot WhatsApp Baileys + bridge HTTP (Node.js)
    config/        penyimpanan kredensial integrasi (server-side)
    database/      model, engine, session
    repositories/  akses data
    services/      logika bisnis
    frontend/      UI dashboard (HTML/JS/CSS)
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

## Konfigurasi (.env)

| Variabel | Wajib | Deskripsi |
|----------|-------|-----------|
| TELEGRAM_TOKEN | Ya | Token bot dari @BotFather |
| AUTHORIZED_USER_ID | Ya | ID user Telegram yang diizinkan (pisahkan koma) |
| DATABASE_URL | Ya | sqlite:///./data/workshop.db (default) |
| UI_ACCESS_TOKEN | Ya (dashboard) | Token akses dashboard/API (bearer) |
| AI_PROVIDER | Tidak | `deepseek` (default) atau `openrouter` |
| DEEPSEEK_API_KEY | Tidak | API key DeepSeek (dipakai bila `AI_PROVIDER=deepseek`) |
| DEEPSEEK_MODEL | Tidak | default deepseek-flash |
| OPENROUTER_API_KEY | Tidak | API key OpenRouter (chat + vision) |
| OPENROUTER_CHAT_MODEL | Tidak | ID model OpenRouter untuk percakapan/tool calling |
| OPENROUTER_VISION_MODEL | Tidak | ID model OpenRouter untuk membaca foto nota |
| APP_HOST | Tidak | default 127.0.0.1 |
| APP_PORT | Tidak | default 8000 |
| BACKUP_DIR | Tidak | default data/backups |

### Pemilihan provider AI

Atur `AI_PROVIDER` untuk memilih provider percakapan & tool calling:

- `AI_PROVIDER=deepseek` (default) → memakai `DEEPSEEK_MODEL`.
- `AI_PROVIDER=openrouter` → memakai `OPENROUTER_CHAT_MODEL`; mode ini **tidak membutuhkan** `DEEPSEEK_API_KEY`.

Foto nota selalu diproses OpenRouter vision (`OPENROUTER_VISION_MODEL`), terlepas dari `AI_PROVIDER`. Model OpenRouter **tidak punya nilai default** — isi ID model yang valid untuk akun Anda (contoh: `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet`). Model chat dan vision boleh berbeda; keduanya memakai satu `OPENROUTER_API_KEY`.

Perilaku saat API key kosong:
- Provider chat terpilih kosong -> AI percakapan memberi tahu belum dikonfigurasi; perintah manual (/daftar, /servis, dll.) tetap berfungsi.
- `OPENROUTER_API_KEY` kosong -> pemrosesan foto memberi tahu fitur belum tersedia; percakapan teks tetap berfungsi.
- OpenRouter dapat dipakai mandiri tanpa `DEEPSEEK_API_KEY` saat `AI_PROVIDER=openrouter`.

Jangan menaruh API key di source code atau commit `.env`. Kredensial integrasi (Telegram/DeepSeek/OpenRouter) dan konfigurasi provider juga bisa dikelola dari dashboard (menu Integrasi) dan disimpan di `data/integration_settings.json` (di-gitignore, tidak pernah disajikan sebagai file statis). Perubahan memerlukan restart untuk aktif.

## WhatsApp CS: perilaku AI

- **Prioritas permintaan terbaru**: AI memproses pesan terbaru lebih dulu; kebutuhan lama hanya dikonfirmasi satu kali dan tidak dianggap disetujui.
- **Estimasi harga**: memeriksa harga jasa dan harga part/bahan terkait (mis. ganti oli mesin memanggil `get_jasa_price` + `get_part_price("oli mesin")`); tidak mengarang harga, stok, atau kuantitas.
- **Part tidak terverifikasi** (mis. "Uppertank"): tidak disamakan dengan part lain dan tidak dikarang; dijelaskan lalu dieskalasi ke owner.
- **Simpan aman**: status/rencana hanya diklaim tersimpan setelah commit berhasil; kegagalan simpan tidak dilaporkan sebagai sukses.
- **Sapaan**: memakai nama bengkel dari dashboard (fallback "Dava Radiator").
- **Delay 5 detik** per balasan, dedup `message_id`, dan isolasi konteks antar nomor.

### Token usage

Provider chat (DeepSeek & OpenRouter) mengembalikan metadata `usage` per respons (`prompt_tokens`, `completion_tokens`, `total_tokens`, `provider`, `model`) bila tersedia; field yang tidak ada di-set `null`. Usage dicatat per respons API (tidak diagregasi otomatis) dan tidak pernah dikirim ke pelanggan.

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

- Suite tes otomatis memakai mock (tanpa panggilan API berbayar). Pengujian AI nyata DeepSeek pernah dilakukan secara terkontrol (database sementara, 9 panggilan) untuk memverifikasi perilaku WhatsApp CS.
- Konfirmasi AI bersifat sementara (in-memory) dan batal saat restart; token terikat pada user dan kedaluwarsa otomatis.

## License

MIT