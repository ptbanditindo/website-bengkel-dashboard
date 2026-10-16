# Laporan Implementasi Backend WhatsApp CS (WA-02 s.d. WA-12)

**Tanggal:** 16 Oktober 2026

## 1. Status Keseluruhan

| Tahap | Status |
|-------|--------|
| WA-02 Database terpisah | PASS |
| WA-03 Service & repository | PASS |
| WA-04 Identitas & keamanan | PASS |
| WA-05 Mesin AI WhatsApp | PARTIAL (agent + tool terkontrol siap; tanpa provider gateway nyata) |
| WA-06 Kandidat ACC/Tolak | PASS |
| WA-07 Rencana kedatangan & antrean owner | PASS |
| WA-08 API & UI | PASS (UI terhubung API; gateway tetap mock) |
| WA-09 Gateway adapter & delay | PASS (abstraksi + mock + antrean per nomor) |
| WA-10 Backup & pemulihan | PASS |
| WA-11 Pengujian otomatis | PASS (29 tes baru, 332 total) |
| WA-12 Audit akhir | PASS (dokumen ini) |

**BLOCKED:** koneksi WhatsApp nyata (provider/gateway belum dipilih pemilik) — sesuai batasan.

## 2. File yang Dibuat

- `whatsapp/__init__.py`
- `whatsapp/models.py` — 6 model (Base terpisah)
- `whatsapp/db.py` — engine + session + `init_whatsapp_db()`
- `whatsapp/normalize.py` — normalisasi nomor telepon
- `whatsapp/services.py` — ContactService, MatchingService, PriceService, CandidateService, ArrivalService, QuestionService, SettingsService
- `whatsapp/agent.py` — prompt + tool terkontrol + WhatsAppAgent
- `whatsapp/gateway.py` — BaseGateway + MockGateway
- `whatsapp/queue.py` — PerNumberQueue (delay per nomor)
- `whatsapp/backup.py` — backup/restore DB WhatsApp
- `api/whatsapp_routes.py` — router endpoint owner
- `tests/test_whatsapp_core.py`, `tests/test_whatsapp_candidates.py`, `tests/test_whatsapp_api.py`, `tests/test_whatsapp_backup.py`

## 3. File yang Diubah

- `api/app.py` — import `init_whatsapp_db` + panggil di `lifespan` + `app.include_router(wa_router)`.
- `tests/conftest.py` — fixture `wa_engine` / `wa_session` (SQLite in-memory terpisah).
- `static/app.js` — halaman WhatsApp CS terhubung ke API (dashboard, inbox, percakapan, pengaturan, ACC/Tolak); data DEMO dihapus.
- `static/index.html` — bump cache `app.js?v=24`.

## 4. Struktur Database WhatsApp (data/whatsapp_cs.db)

| Tabel | Isi |
|-------|-----|
| `wa_contacts` | identitas + memori per nomor + status + `linked_vehicle_id` + `delay_seconds` |
| `wa_messages` | riwayat pesan (dedup `gateway_message_id`) |
| `wa_candidates` | kandidat kendaraan (MENUNGGU_REVIEW / DISETUJUI / DITOLAK) |
| `wa_arrival_plans` | rencana kedatangan (RENCANA / DATANG / TIDAK_DATANG / BATAL) |
| `wa_owner_questions` | antrean pertanyaan owner (MENUNGGU / DIJAWAB / DITUTUP) |
| `wa_agent_settings` | konfigurasi agent (tanpa kredensial) |

## 5. Endpoint API (autentikasi Bearer UI_ACCESS_TOKEN)

- `GET /api/wa/contacts` , `GET /api/wa/contacts/{id}`
- `GET /api/wa/candidates` , `POST /api/wa/candidates/{id}/approve` , `POST /api/wa/candidates/{id}/reject`
- `GET /api/wa/arrivals` , `POST /api/wa/arrivals/{id}/status`
- `GET /api/wa/questions` , `POST /api/wa/questions/{id}/answer` , `POST /api/wa/questions/{id}/close`
- `GET /api/wa/settings` , `PUT /api/wa/settings`
- `GET /api/wa/gateway/status`

## 6. Hasil Tes Aktual

- `pytest` penuh: **332 passed** (303 tes lama + 29 tes WhatsApp baru), 3 warning lama (PTBUserWarning, StarletteDeprecationWarning) — bukan kegagalan.
- Regresi Telegram: seluruh tes lama (auth, AI orchestrator, AI handlers, reporting, read API, vehicle/service/stock service) tetap lulus.

## 7. Konfirmasi Perlindungan

- `data/workshop.db` **tidak di-reset/ditimpa**. Hanya `data/whatsapp_cs.db` yang baru dibuat.
- Migrasi Alembic utama tidak diubah.
- Telegram, `ai/tools.py` (tool Telegram), autentikasi, dan `.env` tidak diubah.
- Tidak ada dependency baru (SQLAlchemy/Alembic/FastAPI sudah ada).
- Tidak ada kredensial/API key di frontend, log, atau respons API.

## 8. Kekurangan / Catatan

- **Gateway WhatsApp nyata belum terhubung** (mock adapter, status jujur `connected:false`). Balasan tidak benar-benar terkirim.
- **Mesin AI WhatsApp** (`WhatsAppAgent.reply`) siap dengan tool terkontrol + DeepSeek, tetapi belum diuji end-to-end dengan pesan masuk nyata karena tanpa gateway. Tool keamanannya sudah diuji unit.
- ACC membuat/menautkan kendaraan di DB utama **tanpa** servis/stok/keuangan (sesuai aturan). Cross-DB (dua file SQLite) tidak atomik sempurna; risiko didokumentasikan.

## 9. Cara Menjalankan Pengujian Lokal

```
python -m pytest -q
```
