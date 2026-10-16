# Rencana SaaS Multi-Tenant — Website Bengkel Dashboard (AI Bengkel)

> Dokumen ini berisi rencana arsitektur untuk mengubah aplikasi dari single-tenant
> menjadi **SaaS multi-tenant** yang dijual ke banyak bengkel. Tiap bengkel (tenant)
> memiliki bot Telegram sendiri, nomor WhatsApp sendiri, dan database sendiri.

## 1. Model Akun

| Akun | Jumlah | Peran | Akses |
|------|--------|-------|-------|
| **Master** | 1 | Super admin | Kelola semua tenant, akun, billing, suspend/aktifkan, reset password |
| **Owner** (user N) | per tenant | Pemilik bengkel | CRUD penuh data bengkelnya sendiri + konfigurasi bot Telegram/WhatsApp |
| **Admin** (admin N) | per tenant | Read-only | Hanya membaca data bengkelnya (tanpa ubah/hapus) |

**Isolasi data:** `owner N` + `admin N` berbagi 1 database tenant N. Antar tenant
terisolasi penuh (database-per-tenant, bukan sekadar filter `tenant_id`).

## 2. Arsitektur Multi-Tenant

```
                    ┌────────── Master Panel (super admin) ──────────┐
                    │  kelola tenant · akun · billing · suspend      │
                    └──────────────────────┬─────────────────────────┘
                                           │
                        Master DB (PostgreSQL) — "control plane"
                    tenants · users · tenant_configs · subscriptions
                                           │
   ┌──────────────┬──────────────┬─────────┴────┬──────────────┬──────────────┐
   ▼              ▼              ▼              ▼              ▼              ▼
Tenant 1       Tenant 2       Tenant 3       Tenant 4       Tenant 5       Tenant N
 DB1            DB2            DB3            DB4            DB5            DBn
 owner1+admin1  owner2+admin2  owner3+admin3  owner4+admin4  owner5+admin5  ownerN+adminN
 bot1           bot2           bot3           bot4           bot5           botN
 WA-session1    WA-session2    WA-session3    WA-session4    WA-session5    WA-sessionN
```

Setiap tenant = 1 database sendiri + 1 bot Telegram sendiri + 1 nomor/sesi WhatsApp
sendiri. `owner` = CRUD penuh, `admin` = hanya baca.

## 3. Keputusan Teknis

| Hal | Pilihan | Alasan |
|-----|---------|--------|
| DB master | **PostgreSQL** | Handal untuk akun/billing, transaksi, concurrency |
| DB tenant | **SQLite file per tenant** (fase 1) | Sesuai "db tiap user berbeda", minim infrastruktur; bisa naik ke Postgres-per-tenant nanti |
| Autentikasi | **JWT + bcrypt** | Login username/password, menggantikan 1 bearer token `UI_ACCESS_TOKEN` |
| Telegram | **1 proses "bot supervisor"** | Jalankan semua bot tenant (python-telegram-bot multi-Application via `asyncio`) |
| WhatsApp | **1 gateway multi-session** | 1 proses Node, map `tenant_id → socket Baileys` (sesi + kredensial per tenant) |
| Secrets tenant | **Terenkripsi** (AES-GCM/Fernet) di `tenant_configs` | Token bot & kredensial WA tiap tenant tidak plaintext |

## 4. Data Model Master (baru)

- `tenants` — id, slug, nama_bengkel, plan, status (active/suspended), expired_at, created_at.
- `users` — id, tenant_id (null = master), username, password_hash, role (`master`/`owner`/`admin`), is_active.
- `tenant_configs` — telegram_token (encrypted), authorized_user_ids, whatsapp_credentials (encrypted), db_name.
- `subscriptions` — (fase 4) plan, pembayaran, invoice.

## 5. Perubahan Kode per Komponen

1. **Auth & RBAC (web/api)**
   - Login + JWT; dependency baru `get_current_user` + `require_role(...)` menggantikan `require_ui_access`.
   - Guard "read-only": blokir POST/PUT/DELETE untuk role `admin`.
   - Setiap query resolve database berdasarkan `tenant_id` user.

2. **Isolasi database per tenant**
   - `get_db()` / `get_whatsapp_db()` menjadi tenant-aware (engine per tenant, di-cache).
   - Saat tenant dibuat → buat DB tenant + jalankan `alembic upgrade head`.
   - Saat app start → migrasi DB master + semua DB tenant.

3. **Panel Master (endpoint + UI baru)**
   - CRUD tenant, CRUD user (owner/admin), suspend/aktifkan, reset password, billing manual, impersonate.

4. **Panel Tenant (owner vs admin)**
   - Owner: semua fitur saat ini (kendaraan, servis, stok, harga jasa, garansi, backup, dsb.).
   - Admin: tampilan read-only.

5. **Telegram bot per tenant (bot supervisor)**
   - Proses tunggal membaca tenant aktif dari master DB, jalankan 1 bot per tenant (token + DB sendiri).

6. **WhatsApp multi-session gateway**
   - Tulis ulang `gateway/whatsapp_bridge.js`: kelola banyak sesi Baileys (1 per tenant), kredensial & folder sesi per tenant, webhook inbound diteruskan ke tenant yang benar.

7. **Migrasi Alembic per tenant**
   - Template schema yang sama, diterapkan per DB tenant.

## 6. Konfigurasi per Tenant (self-service)

- **Owner** login ke dashboard tenant → menu **Integrasi** → masukkan token bot Telegram
  (dari @BotFather) + link WhatsApp (scan QR / pairing code dari HP-nya).
- **Admin (read-only)** tidak bisa mengubah integrasi.
- **Master** hanya mengelola tenant/akun/billing — tidak menyentuh token tenant,
  tapi bisa melihat status koneksi tiap tenant.

## 7. Deployment (Docker Compose)

```yaml
services:
  web:            # FastAPI (semua tenant) + static dashboard
  bot-supervisor: # semua bot Telegram tenant
  wa-gateway:     # multi-session Baileys (internal only)
  postgres:       # master DB
  caddy:          # HTTPS + domain (satu-satunya pintu publik)
volumes:
  tenant-data:    # DB SQLite + sesi WA per tenant
  postgres-data:
```

## 8. Fase Implementasi

1. **Fase 1 — Fondasi SaaS** (paling penting): login + JWT + RBAC, tabel
   `tenants`/`users`/`tenant_configs`, isolasi database per tenant, panel master +
   panel tenant (owner CRUD / admin read-only).
2. **Fase 2 — Telegram per tenant**: bot supervisor (N bot, N token, N DB).
3. **Fase 3 — WhatsApp per tenant**: gateway multi-session (N nomor, N sesi, QR per tenant).
4. **Fase 4 — Monetisasi**: integrasi pembayaran (Midtrans/Xendit), expired/auto-suspend, invoice.
