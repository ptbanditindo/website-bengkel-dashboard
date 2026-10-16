# Laporan H6A — Optimasi API Aman untuk record_service_visit

## Status Akhir: **PASS**

Optimasi terbukti mengurangi satu request model untuk alur `record_service_visit`
(dibuktikan dengan mock provider), seluruh regresi lulus, konfirmasi & atomisitas
tetap aman, dan alur legacy tidak rusak.

---

## 1. Kondisi Sebelum (temuan H4/H5)

Satu instruksi pencatatan memakai 3 request model bila model membaca dulu, atau 2
request bila langsung memakai `record_service_visit`:

| Alur | Request sebelum |
|------|----------------|
| langsung `record_service_visit` | 2 (tool call + jawaban akhir) |
| baca dulu + `record_service_visit` | 3 (baca + tool call + jawaban akhir) |

Request "jawaban akhir" **terbukti terbuang** — orchestrator mengembalikan
`summary` (bukan `content` model) ketika ada pending action.

## 2. Kondisi Sesudah

Optimasi hanya menyentuh `record_service_visit` (operasi atomik lengkap). Saat
`record_service_visit` menjadi satu-satunya pending step, loop berhenti dan
pending action dikembalikan segera — tanpa request jawaban akhir.

| Alur | Request sebelum | Request sesudah |
|------|:---------------:|:---------------:|
| langsung `record_service_visit` | 2 | **1** |
| baca dulu + `record_service_visit` | 3 | **2** |
| legacy `create_vehicle` (+ `add_service_record`) | 2 | 2 (tidak berubah) |

## 3. Perubahan Kode & Alasan

- **`ai/orchestrator.py`**
  - Tambah helper `_finalize_pending()` (deduplikasi 3 titik kembalian pending action).
  - Tambah pengecekan pasca-proses tool call:
    ```python
    if pending_steps and all(s["tool"] == "record_service_visit" for s in pending_steps):
        return self._finalize_pending(...)
    ```
  - **Hanya** `record_service_visit` yang memicu penghentian dini; alur legacy
    (multi-langkah, mutasi lain) tetap memakai loop penuh.
- **`tests/test_ai_orchestrator.py`** — 3 test baru (bukti mock).

Alasan: request jawaban akhir setelah `record_service_visit` tidak pernah dipakai;
`record_service_visit` adalah satu operasi atomik lengkap sehingga tidak ada
langkah mutasi lanjutan yang perlu dikumpulkan.

## 4. Bukti Penghematan (mock provider, deterministik — tanpa API)

| Test | Bukti |
|------|-------|
| `test_record_service_visit_skips_final_answer_call` | `len(provider.calls) == 1` (tanpa jawaban akhir) |
| `test_record_service_visit_with_prior_read_uses_two_calls` | `len(provider.calls) == 2` (baca + mutasi, tanpa jawaban akhir) |
| `test_legacy_create_vehicle_still_uses_final_answer` | `len(provider.calls) == 2` (legacy tetap meminta jawaban akhir) |
| `test_handle_message_collects_combined_mutations` | 2 langkah `create_vehicle`+`add_service_record` tetap terkumpul |

## 5. Keamanan (tidak berubah / tetap terverifikasi)

- Pending action tetap menunggu konfirmasi eksplisit (tidak ada mutasi di `handle_message`).
- Tidak ada mutasi prematur (`session.query(...).count() == 0` sebelum konfirmasi).
- Konfirmasi menghasilkan 1 kendaraan + 1 riwayat servis (atomik).
- Pembatalan tidak mengubah database.
- Rollback atomik tetap aman (test `test_execute_pending_rolls_back_when_second_step_fails`).
- Pending action terisolasi per pengguna, kedaluwarsa, sekali pakai.
- Tool laporan & pencarian tidak regresi.

## 6. Regresi

- `python -m pytest -q` → **155 passed, 0 failed, 0 skipped** (152 + 3 baru).

## 7. Status Database Operasional

- `data/workshop.db` **tidak berubah** (read-only: 1 kendaraan, 0 servis).

## 8. Keterbatasan

- Penghematan dibuktikan dengan mock provider (deterministik), bukan live API —
  sesuai instruksi (jumlah request diukur lewat mock, bukan API nyata).
- Tidak ada live test H6A (tidak diperlukan; perilaku fungsional sudah dibuktikan
  oleh test + live H4/H5).

## 9. Kesimpulan

Optimasi aman & terbukti: alur `record_service_visit` kini hemat 1 request, alur
legacy tetap utuh, konfirmasi & atomisitas aman, dan seluruh regresi lulus.
