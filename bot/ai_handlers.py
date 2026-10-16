"""AI-driven handlers: natural-language chat, photo extraction, confirmation."""

import json
import logging
from decimal import Decimal

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ai.errors import AIError, AIProviderError
from bot.ai_runtime import get_runtime
from bot.auth import require_auth
from database.models import normalize_plate
from database.session import SessionLocal
from services.exceptions import ServiceError
from services.pricing import parse_money
from services.vehicle_service import VehicleService

logger = logging.getLogger(__name__)

IMAGE_EXTRACTION_PROMPT = (
    "Baca foto ini sebagai nota/dokumen bengkel. Ekstrak hanya informasi yang "
    "benar-benar terbaca. Tandai field yang tidak jelas sebagai kosong. Kembalikan "
    "JSON dengan kunci: plat (nomor polisi), nama_client, jobs (daftar objek "
    "{deskripsi, jumlah, harga}), parts (daftar objek {nama_part, jumlah, "
    "harga_satuan}), total (total nota, opsional), garansi_sampai (YYYY-MM-DD), "
    "catatan. Jangan mengarang angka."
)

MAX_TEXT_LENGTH = 2000
MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_REPLY_LENGTH = 4000
JPEG_MAGIC = b"\xff\xd8\xff"


def _is_jpeg(data: bytes) -> bool:
    return data[:3] == JPEG_MAGIC


def _truncate(text: str, max_len: int = MAX_REPLY_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n…(terpotong)"


def _parse_json(text: str):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


@require_auth
async def ai_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    if len(text) > MAX_TEXT_LENGTH:
        await update.message.reply_text(f"❌ Pesan terlalu panjang (maks {MAX_TEXT_LENGTH} karakter).")
        return

    runtime = get_runtime()

    # Continue a pending photo draft (awaiting the plate number).
    draft = runtime.photo_drafts.pop(update.effective_user.id)
    if draft is not None:
        await _process_photo_plate(update, text, draft.data)
        return

    if not runtime.deepseek.configured:
        await update.message.reply_text(
            "❌ AI belum dikonfigurasi (DEEPSEEK_API_KEY kosong).\n"
            "Anda tetap bisa memakai perintah manual: /daftar, /servis, /cari, /riwayat, /garansi."
        )
        return

    history = runtime.conversations.get(update.effective_user.id)
    session = SessionLocal()
    try:
        result = await runtime.orchestrator.handle_message(
            text, session, history, user_id=update.effective_user.id
        )
    finally:
        session.close()

    if result.pending_action is not None:
        keyboard = [[
            InlineKeyboardButton("✅ Konfirmasi", callback_data=f"ai_confirm_{result.pending_action.token}"),
            InlineKeyboardButton("❌ Batal", callback_data=f"ai_cancel_{result.pending_action.token}"),
        ]]
        await update.message.reply_text(
            "Konfirmasi perubahan:\n\n" + _truncate(result.reply),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.message.reply_text(_truncate(result.reply))


@require_auth
async def ai_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    token = query.data.split("ai_confirm_")[1]
    session = SessionLocal()
    try:
        result_text = get_runtime().orchestrator.execute_pending(
            token, session, user_id=update.effective_user.id
        )
        await query.edit_message_text("✅ Berhasil:\n\n" + result_text)
        # A finished transaction must not leak into the next one: reset the
        # per-user conversation history so a later message starts fresh.
        get_runtime().conversations.reset(update.effective_user.id)
    except AIError as e:
        await query.edit_message_text(f"❌ {e}")
    except ServiceError as e:
        await query.edit_message_text(f"❌ {e}")
    except Exception:
        logger.exception("Gagal mengeksekusi konfirmasi AI")
        await query.edit_message_text("❌ Terjadi kesalahan. Data tidak tersimpan.")
    finally:
        session.close()


@require_auth
async def ai_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    token = query.data.split("ai_cancel_")[1]
    removed = get_runtime().pending_store.pop(token, update.effective_user.id)
    if removed is not None:
        await query.edit_message_text("❌ Dibatalkan. Tidak ada data yang disimpan.")
        # An abandoned transaction should not contaminate the next message.
        get_runtime().conversations.reset(update.effective_user.id)
    else:
        await query.edit_message_text("❌ Konfirmasi tidak valid, kedaluwarsa, atau bukan milik Anda.")


@require_auth
async def ai_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    runtime = get_runtime()
    if not runtime.gemini.configured:
        await update.message.reply_text(
            "📷 Pemrosesan gambar belum tersedia (GEMINI_API_KEY kosong).\n"
            "Anda bisa mencatat servis manual lewat /servis."
        )
        return

    photo = update.message.photo[-1]
    if (photo.file_size or 0) > MAX_PHOTO_BYTES:
        await update.message.reply_text("❌ Foto terlalu besar (maks 5 MB).")
        return
    file = await photo.get_file()
    image_bytes = bytes(await file.download_as_bytearray())

    if len(image_bytes) > MAX_PHOTO_BYTES:
        await update.message.reply_text("❌ Foto terlalu besar (maks 5 MB).")
        return
    if not _is_jpeg(image_bytes):
        await update.message.reply_text("❌ Format foto tidak didukung (hanya JPEG).")
        return

    try:
        raw = await runtime.gemini.extract(image_bytes, "image/jpeg", IMAGE_EXTRACTION_PROMPT)
    except AIProviderError as e:
        await update.message.reply_text(f"❌ {e}\nGunakan input manual: /servis")
        return

    data = _parse_json(raw)
    if not data:
        await update.message.reply_text("❌ Tidak dapat membaca foto ini. Gunakan input manual: /servis")
        return

    # Plate from caption (preferred) or from the extracted nota.
    plate = (update.message.caption or "").strip() or (data.get("plat") or data.get("nopol") or "").strip()

    if not plate:
        runtime.photo_drafts.add(update.effective_user.id, data)
        await update.message.reply_text("Silakan kirim nomor plat kendaraan, misalnya B 1431 CVD.")
        return

    await _process_photo_plate(update, plate, data)


def _coerce_money(value):
    """Coerce a money expression to Decimal; None when absent/unparseable."""
    if value is None:
        return None
    try:
        return parse_money(value)
    except Exception:
        return None


def _sum_item_prices(jobs, parts):
    """Sum item prices (harga x jumlah); None when any price is unknown."""
    total = Decimal("0")
    for item in list(jobs or []) + list(parts or []):
        if not isinstance(item, dict):
            return None
        qty = item.get("jumlah", 1)
        price = item.get("harga") if "harga" in item else item.get("harga_satuan")
        val = _coerce_money(price)
        if val is None:
            return None
        try:
            total += val * Decimal(int(qty))
        except (TypeError, ValueError):
            return None
    return total


def _fmt_money(value) -> str:
    if value is None:
        return "0"
    return f"{value:,.0f}".replace(",", ".")


def _build_service_draft(data: dict):
    """Build a summary and add_service_record arguments from extracted data."""
    plat = (data.get("plat") or data.get("nopol") or "").strip()
    jobs = data.get("jobs") or []
    parts = data.get("parts") or []
    garansi = data.get("garansi_sampai") or None
    catatan = data.get("catatan") or None

    lines = ["Hasil ekstraksi foto:"]
    lines.append(f"• Plat: {plat or 'TIDAK JELAS'}")
    for j in jobs:
        lines.append(f"• Pekerjaan: {j.get('deskripsi')} x{j.get('jumlah', 1)} @ {j.get('harga', '-')}")
    for p in parts:
        lines.append(f"• Part: {p.get('nama_part')} x{p.get('jumlah', 1)} @ {p.get('harga_satuan', '-')}")
    lines.append(f"• Garansi s/d: {garansi or '-'}")

    # Cross-check the extracted total (if any) against the item sum. Purely
    # diagnostic: storage still derives the total from the items.
    total_val = _coerce_money(data.get("total"))
    if total_val is not None:
        item_sum = _sum_item_prices(jobs, parts)
        if item_sum is not None:
            if total_val != item_sum:
                lines.append(f"⚠️ Total nota {_fmt_money(total_val)} tidak cocok dengan jumlah rincian {_fmt_money(item_sum)}.")
            else:
                lines.append(f"• Total: {_fmt_money(total_val)} (cocok dengan rincian)")

    arguments = {
        "jobs": jobs,
        "parts": parts,
        "garansi_sampai": garansi,
        "catatan": catatan,
    }
    return "\n".join(lines), arguments


def _photo_confirm_summary(nopol: str, vehicle_exists: bool, data: dict) -> str:
    """Full draft summary shown before the user confirms a photo-based record."""
    lines = [
        "Periksa data servis sebelum menyimpan:",
        f"• Status: {'kendaraan terdaftar' if vehicle_exists else 'kendaraan baru'}",
        f"• Plat: {nopol}",
        "• Nama klien: Belum diisi",
        "• WhatsApp: Belum diisi",
        "",
        "Rincian servis:",
    ]
    for j in data.get("jobs") or []:
        lines.append(f"- {j.get('deskripsi')} x{j.get('jumlah', 1)} @ {j.get('harga') or '-'}")
    for p in data.get("parts") or []:
        lines.append(f"- {p.get('nama_part')} x{p.get('jumlah', 1)} @ {p.get('harga_satuan') or '-'}")
    item_sum = _sum_item_prices(data.get("jobs") or [], data.get("parts") or [])
    if item_sum is not None:
        lines.append(f"• Total rincian: {_fmt_money(item_sum)}")
    total_val = _coerce_money(data.get("total"))
    if total_val is not None:
        if item_sum is not None and total_val != item_sum:
            lines.append(f"⚠️ Total nota {_fmt_money(total_val)} tidak cocok dengan jumlah rincian {_fmt_money(item_sum)}.")
        else:
            lines.append(f"• Total nota: {_fmt_money(total_val)}")
    if data.get("garansi_sampai"):
        lines.append(f"• Garansi s/d: {data.get('garansi_sampai')}")
    return "\n".join(lines)


async def _process_photo_plate(update: Update, plate_text: str, data: dict):
    """Resolve a plate and build a pending action (existing or new vehicle)."""
    runtime = get_runtime()
    nopol = normalize_plate(plate_text)
    if not nopol:
        await update.message.reply_text("❌ Nomor plat tidak valid. Kirim plat yang benar, misalnya B 1431 CVD.")
        return

    session = SessionLocal()
    try:
        vehicle = VehicleService(session).find_vehicle_by_plate(nopol)
    finally:
        session.close()

    vehicle_exists = vehicle is not None
    _, arguments = _build_service_draft(data)
    summary = _photo_confirm_summary(nopol, vehicle_exists, data)

    if vehicle_exists:
        steps = [{"tool": "add_service_record", "arguments": {"vehicle_id": vehicle.id, **arguments}}]
    else:
        steps = [{"tool": "record_service_visit", "arguments": {
            "nopol": nopol,
            "nama_client": None,
            "nomor_wa": None,
            "jenis_mobil": None,
            "tahun_mobil": None,
            "alamat_client": None,
            **arguments,
        }}]

    action = runtime.pending_store.add(update.effective_user.id, steps, summary)
    keyboard = [[
        InlineKeyboardButton("✅ Simpan", callback_data=f"ai_confirm_{action.token}"),
        InlineKeyboardButton("❌ Batal", callback_data=f"ai_cancel_{action.token}"),
    ]]
    await update.message.reply_text(
        summary + "\n\nPeriksa data di atas sebelum menyimpan.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

