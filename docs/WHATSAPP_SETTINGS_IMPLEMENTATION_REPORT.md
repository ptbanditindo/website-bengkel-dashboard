# Laporan Implementasi Pengaturan Integrasi + WhatsApp Baileys (WA-SETTINGS-02)

**Tanggal:** 16 Oktober 2026

## Status

| Bagian | Status |
|--------|--------|
| Penyimpanan rahasia (config store) | PASS |
| API pengaturan (status/save/test/delete) | PASS |
| UI Pengaturan Integrasi | PASS |
| Telegram token (getMe) | PASS |
| DeepSeek / Gemini key (test + save) | PASS (uji nyata saat owner memicu; tes pakai mock) |
| Gateway Baileys (Node.js) | PARTIAL — bridge nyata dibuat & dependensi terpasang; autentikasi QR/pairing nyata belum diuji (butuh akun/perangkat) |
| Integrasi pesan end-to-end (inbound -> AI -> kirim) | PARTIAL — alur dibuat; pengiriman nyata butuh gateway terautentikasi |
| Pengujian otomatis | PASS — 342 tes lulus (10 tes baru + 332 lama) |

**BLOCKED:** autentikasi WhatsApp nyata (scan QR / pairing akun nyata) tidak dilakukan — tidak ada kredensial/perangkat pemilik.

## Dependency & Versi
- Node.js v22.14.0, npm 11.11.0 (tersedia di runtime).
- `@whiskeysockets/baileys` 6.7.24 (baris stabil v6).
- `pino` 8.21.0 (logging), `qrcode` 1.5.4 (render QR ke data URI).
- Tidak ada dependency Python baru.

## Cara Menjalankan Gateway Node.js
```
cd Telegram-Finance-Bot/gateway
npm install          # sudah dilakukan (136 paket)
node whatsapp_bridge.js
```
- Bind `127.0.0.1:9090` (env `BAILEYS_PORT`).
- Sesi disimpan di `data/baileys_session/` (persisten, dipulihkan saat restart).
- Token internal dibaca dari `data/integration_settings.json` (`whatsapp_internal_token`).
- Pesan masuk di-POST ke `http://127.0.0.1:8000/api/integrations/whatsapp/inbound` dengan header `Authorization: Bearer <token internal>`.

## Cara Membuka Pengaturan Integrasi
Buka UI bengkel -> menu sidebar **"Integrasi"** (ikon gerigi).

## Mekanisme Penyimpanan Rahasia & Sesi
- Rahasia (`telegram_bot_token`, `deepseek_api_key`, `gemini_api_key`, `whatsapp_internal_token`) disimpan server-side di `data/integration_settings.json` (privat, tidak disajikan sebagai static, di-ignore Git).
- Endpoint GET **tidak pernah** mengembalikan nilai rahasia — hanya status tersamarkan (`stored/active/masked/needs_restart`).
- Sesi Baileys disimpan di `data/baileys_session/` (direktori privat, di-ignore Git).
- Runtime tetap membaca `.env`; nilai yang disimpan lewat UI butuh **restart** untuk aktif (ditandai `needs_restart`).

## Endpoint Baru (autentikasi Bearer `UI_ACCESS_TOKEN`, kecuali inbound)
- `GET /api/integrations/status`
- `POST /api/integrations/telegram/save|test|delete`
- `POST /api/integrations/deepseek/save|test|delete`
- `POST /api/integrations/gemini/save|test|delete`
- `GET /api/integrations/whatsapp/status`
- `POST /api/integrations/whatsapp/qr/start`
- `POST /api/integrations/whatsapp/pairing/request`
- `POST /api/integrations/whatsapp/logout`
- `POST /api/integrations/whatsapp/inbound` (auth token internal, dipanggil bridge Baileys)

## Scan QR & Kode Pairing
- **Scan QR:** jalankan `node gateway/whatsapp_bridge.js`, buka menu Integrasi -> klik **Mulai Scan QR**. QR asli dari Baileys di-poll dan ditampilkan sebagai gambar. Status: menunggu scan / terhubung / kedaluwarsa / gagal.
- **Kode Pairing:** masukkan nomor (normalisasi `0` -> `62`), klik **Minta Kode Pairing**; kode asli dari `sock.requestPairingCode` ditampilkan (bukan buatan).

## Cara Menguji
- **Telegram:** isi token -> **Uji Koneksi** (memakai `getMe`). Simpan hanya jika valid; token invalid tidak menggantikan token lama.
- **DeepSeek/Gemini:** isi key -> **Uji Koneksi** (ping API). Simpan/Hapus eksplisit.

## Hasil Tes Aktual
- `pytest -q`: **342 passed, 0 failed** (10 tes integrasi baru + 332 tes lama).
- `node --check gateway/whatsapp_bridge.js`: OK.
- Tes memakai mock gateway + kredensial uji; **tidak** scan QR akun pribadi, **tidak** kirim pesan nyata, **tidak** menyentuh `data/workshop.db` atau sesi produksi.

## Status Integrasi Pesan End-to-End
Alur (inbound -> validasi metadata -> dedup -> simpan -> WhatsAppAgent -> balasan -> kirim) **terpasang** dan inbound+dedup diuji dengan mock. **Pengiriman nyata belum diuji** karena gateway belum terautentikasi ke akun nyata.

## Langkah Manual yang Masih Diperlukan
1. Jalankan `node gateway/whatsapp_bridge.js`.
2. Scan QR / pairing dengan akun WhatsApp milik owner (tindakan eksplisit pemilik).
3. Setelah terhubung, uji pesan masuk nyata.
4. Restart bot/API setelah menyimpan token/key agar `.env` yang aktif tergantikan oleh nilai tersimpan (sesuai kebijakan owner).

## Risiko & Keterbatasan
- Baileys adalah library tidak resmi; protokol WhatsApp dapat berubah dan tidak ada jaminan kompatibilitas permanen.
- Sesi Baileys (kredensial) hanya di `data/baileys_session/` — jangan di-commit atau dibagikan.
- Komunikasi FastAPI <-> Node hanya di localhost dengan token internal; tidak dibuka ke publik.
- Kode pairing/QR/status tidak dicatat ke log.
