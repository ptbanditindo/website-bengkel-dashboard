"""Telegram handlers for the AI Bengkel bot (structured/manual flow).

Business rules and money math live in the service layer; handlers only
orchestrate the conversation and render results. DeepSeek/AI natural-language
integration is added in a later phase.
"""

import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.auth import require_auth
from bot.formatting import format_service_record, format_vehicle, format_warranty
from bot.parsing import extract_plate, parse_item_lines, parse_optional_date
from database.models import normalize_plate
from database.session import SessionLocal
from services.catalog import catalog_price_warnings
from services.exceptions import ConflictError, NotFoundError, ValidationError
from services.service_record_service import ServiceRecordService
from services.validation import normalize_required_plate, validate_tahun
from services.vehicle_service import VehicleService

logger = logging.getLogger(__name__)

# Conversation states — vehicle registration
REG_NAME, REG_PLATE, REG_WA, REG_TYPE, REG_YEAR, REG_ADDRESS, REG_CONFIRM = range(7)
# Conversation states — service record
SVC_PLATE, SVC_JOBS, SVC_PARTS, SVC_WARRANTY, SVC_NOTES, SVC_CONFIRM = range(6)

# Cancellation keywords (case-insensitive) and form-input filter.
CANCEL_REGEX = re.compile(r"^(batal|cancel|tidak jadi)$", re.IGNORECASE)
FORM_TEXT_FILTER = filters.TEXT & ~filters.COMMAND & ~filters.Regex(CANCEL_REGEX)
CANCEL_FILTER = filters.TEXT & ~filters.COMMAND & filters.Regex(CANCEL_REGEX)


def _session():
    return SessionLocal()


def _plate_from_args(args) -> str | None:
    if not args:
        return None
    return " ".join(args)


# ---------------------------------------------------------------------------
# Simple commands
# ---------------------------------------------------------------------------
@require_auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔧 *AI Bengkel Bot*\n\n"
        "Perintah yang tersedia:\n"
        "/daftar — daftarkan kendaraan baru\n"
        "/servis — catat riwayat servis\n"
        "/cari <plat> — cari kendaraan\n"
        "/riwayat <plat> — lihat riwayat servis\n"
        "/garansi <plat> — lihat status garansi\n"
        "/klaim <plat> — ubah status klaim garansi\n"
        "/hapus <plat> — hapus kendaraan\n"
        "/help — bantuan"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@require_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🔍 *Cara Menggunakan AI Bengkel*\n\n"
        "1️⃣ Daftarkan kendaraan: /daftar\n"
        "2️⃣ Catat servis: /servis\n"
        "3️⃣ Cari kendaraan: /cari B 1234 ABC\n"
        "4️⃣ Riwayat servis: /riwayat B 1234 ABC\n"
        "5️⃣ Status garansi: /garansi B 1234 ABC\n"
        "6️⃣ Klaim garansi: /klaim B 1234 ABC\n"
        "7️⃣ Hapus kendaraan: /hapus B 1234 ABC\n\n"
        "Satu plat nomor = satu data kendaraan."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@require_auth
async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your Telegram user ID: {update.effective_user.id}")


@require_auth
async def cmd_cari(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plate = _plate_from_args(context.args)
    if not plate:
        await update.message.reply_text("Format: /cari <nomor polisi>")
        return
    session = _session()
    try:
        vehicle = VehicleService(session).find_vehicle_by_plate(plate)
    finally:
        session.close()
    if vehicle is None:
        await update.message.reply_text(f"❌ Kendaraan dengan plat {normalize_plate(plate)} tidak ditemukan.")
        return
    await update.message.reply_text(format_vehicle(vehicle))


@require_auth
async def cmd_riwayat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plate = _plate_from_args(context.args)
    if not plate:
        await update.message.reply_text("Format: /riwayat <nomor polisi>")
        return
    session = _session()
    try:
        vehicle = VehicleService(session).find_vehicle_by_plate(plate)
        if vehicle is None:
            await update.message.reply_text(f"❌ Kendaraan dengan plat {normalize_plate(plate)} tidak ditemukan.")
            return
        records = ServiceRecordService(session).list_service_records(vehicle.id)
    finally:
        session.close()
    if not records:
        await update.message.reply_text("Belum ada riwayat servis untuk kendaraan ini.")
        return
    await update.message.reply_text("\n\n".join(format_service_record(r) for r in records))


@require_auth
async def cmd_garansi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plate = _plate_from_args(context.args)
    if not plate:
        await update.message.reply_text("Format: /garansi <nomor polisi>")
        return
    session = _session()
    try:
        vehicle = VehicleService(session).find_vehicle_by_plate(plate)
        if vehicle is None:
            await update.message.reply_text(f"❌ Kendaraan dengan plat {normalize_plate(plate)} tidak ditemukan.")
            return
        records = ServiceRecordService(session).list_service_records(vehicle.id)
    finally:
        session.close()
    if not records:
        await update.message.reply_text("Belum ada riwayat servis untuk kendaraan ini.")
        return
    await update.message.reply_text("\n\n".join(format_warranty(r) for r in records))


# ---------------------------------------------------------------------------
# Warranty claim flow (command + callbacks)
# ---------------------------------------------------------------------------
@require_auth
async def cmd_klaim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plate = _plate_from_args(context.args)
    if not plate:
        await update.message.reply_text("Format: /klaim <nomor polisi>")
        return
    session = _session()
    try:
        records = ServiceRecordService(session).get_vehicle_service_history(plate)
    except NotFoundError as e:
        await update.message.reply_text(f"❌ {e}")
        return
    finally:
        session.close()
    if not records:
        await update.message.reply_text("Tidak ada riwayat servis untuk kendaraan ini.")
        return
    keyboard = [
        [InlineKeyboardButton(f"Servis {r.waktu_service.strftime('%d/%m/%Y')}", callback_data=f"klaim_{r.id}")]
        for r in records
    ]
    await update.message.reply_text(
        "Pilih riwayat servis yang akan diklaim garansinya:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def select_klaim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    record_id = int(query.data.split("_")[1])
    session = _session()
    try:
        record = ServiceRecordService(session).get_service_record(record_id)
    except NotFoundError:
        await query.edit_message_text("❌ Riwayat servis tidak ditemukan.")
        return
    finally:
        session.close()
    keyboard = [[
        InlineKeyboardButton("✅ Ya, klaim", callback_data=f"confirm_klaim_{record_id}"),
        InlineKeyboardButton("❌ Batal", callback_data="cancel_klaim"),
    ]]
    await query.edit_message_text(
        f"Konfirmasi klaim garansi untuk servis tanggal {record.waktu_service.strftime('%d/%m/%Y')}?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def confirm_klaim_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    record_id = int(query.data.split("confirm_klaim_")[1])
    session = _session()
    try:
        record = ServiceRecordService(session).mark_claim(record_id)
        await query.edit_message_text(
            f"✅ Status klaim berhasil diubah menjadi Sudah claim.\n\n{format_service_record(record)}",
        )
    except NotFoundError as e:
        await query.edit_message_text(f"❌ {e}")
    except Exception:
        logger.exception("Gagal mengubah status klaim")
        await query.edit_message_text("❌ Gagal memperbarui status klaim. Data tidak berubah.")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Delete vehicle flow (command + callback)
# ---------------------------------------------------------------------------
@require_auth
async def cmd_hapus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plate = _plate_from_args(context.args)
    if not plate:
        await update.message.reply_text("Format: /hapus <nomor polisi>")
        return
    session = _session()
    try:
        vehicle = VehicleService(session).find_vehicle_by_plate(plate)
    finally:
        session.close()
    if vehicle is None:
        await update.message.reply_text(f"❌ Kendaraan dengan plat {normalize_plate(plate)} tidak ditemukan.")
        return
    keyboard = [[
        InlineKeyboardButton("✅ Ya, hapus", callback_data=f"confirm_delete_{vehicle.id}"),
        InlineKeyboardButton("❌ Batal", callback_data="cancel_delete"),
    ]]
    await update.message.reply_text(
        f"Yakin hapus kendaraan ini?\n\n{format_vehicle(vehicle)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


@require_auth
async def confirm_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    vehicle_id = int(query.data.split("confirm_delete_")[1])
    session = _session()
    try:
        VehicleService(session).delete_vehicle(vehicle_id)
        await query.edit_message_text("✅ Kendaraan berhasil dihapus.")
    except ConflictError as e:
        await query.edit_message_text(f"❌ {e}")
    except NotFoundError as e:
        await query.edit_message_text(f"❌ {e}")
    except Exception:
        logger.exception("Gagal menghapus kendaraan")
        await query.edit_message_text("❌ Terjadi kesalahan saat menghapus kendaraan.")
    finally:
        session.close()


@require_auth
async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Dibatalkan.")


# ---------------------------------------------------------------------------
# Vehicle registration conversation
# ---------------------------------------------------------------------------
@require_auth
async def cmd_daftar_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plate = extract_plate(" ".join(context.args)) if context.args else None
    if plate:
        try:
            nopol = normalize_required_plate(plate)
        except ValidationError:
            nopol = None
        if nopol:
            session = _session()
            try:
                if VehicleService(session).find_vehicle_by_plate(nopol) is not None:
                    await update.message.reply_text(
                        f"❌ Kendaraan dengan plat {nopol} sudah terdaftar. Gunakan /cari."
                    )
                    return ConversationHandler.END
            finally:
                session.close()
            context.user_data["reg_nopol"] = nopol
            await update.message.reply_text("Nomor WA client? (ketik '-' jika tidak ada)")
            return REG_WA
    await update.message.reply_text("Siapa nama client? (ketik '-' jika tidak ada)")
    return REG_NAME


@require_auth
async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data["reg_name"] = None if (not name or name == "-") else name
    await update.message.reply_text("Nomor polisi kendaraan? (contoh: B 1234 ABC)")
    return REG_PLATE


@require_auth
async def reg_plate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        nopol = normalize_required_plate(update.message.text)
    except ValidationError as e:
        await update.message.reply_text(f"❌ {e} Ketik ulang:")
        return REG_PLATE
    session = _session()
    try:
        if VehicleService(session).find_vehicle_by_plate(nopol) is not None:
            await update.message.reply_text(f"❌ Kendaraan dengan plat {nopol} sudah terdaftar. Gunakan /cari.")
            return ConversationHandler.END
    finally:
        session.close()
    context.user_data["reg_nopol"] = nopol
    await update.message.reply_text("Nomor WA client? (ketik '-' jika tidak ada)")
    return REG_WA


@require_auth
async def reg_wa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["reg_wa"] = None if (not text or text == "-") else text
    await update.message.reply_text("Jenis mobil? (contoh: Toyota Avanza, ketik '-' jika tidak ada)")
    return REG_TYPE


@require_auth
async def reg_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["reg_type"] = None if (not text or text == "-") else text
    await update.message.reply_text("Tahun mobil? (contoh: 2020, ketik '-' jika tidak ada)")
    return REG_YEAR


@require_auth
async def reg_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text and text != "-":
        try:
            year = validate_tahun(text)
        except ValidationError as e:
            await update.message.reply_text(f"❌ {e} Ketik ulang:")
            return REG_YEAR
    else:
        year = None
    context.user_data["reg_year"] = year
    await update.message.reply_text("Alamat client? (ketik '-' jika tidak ada)")
    return REG_ADDRESS


@require_auth
async def reg_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["reg_address"] = None if (not text or text == "-") else text
    summary = (
        "Konfirmasi data kendaraan:\n\n"
        f"👤 Nama: {context.user_data.get('reg_name') or '-'}\n"
        f"🚗 Plat: {context.user_data['reg_nopol']}\n"
        f"📱 WA: {context.user_data.get('reg_wa') or '-'}\n"
        f"🔧 Jenis: {context.user_data.get('reg_type') or '-'}\n"
        f"📅 Tahun: {context.user_data.get('reg_year') or '-'}\n"
        f"📍 Alamat: {context.user_data.get('reg_address') or '-'}"
    )
    keyboard = [[
        InlineKeyboardButton("✅ Simpan", callback_data="reg_save"),
        InlineKeyboardButton("❌ Batal", callback_data="reg_cancel"),
    ]]
    await update.message.reply_text(summary, reply_markup=InlineKeyboardMarkup(keyboard))
    return REG_CONFIRM


@require_auth
async def confirm_register_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "reg_cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ Pendaftaran dibatalkan.")
        return ConversationHandler.END
    session = _session()
    try:
        vehicle = VehicleService(session).create_vehicle(
            nama_client=context.user_data.get("reg_name"),
            nopol=context.user_data["reg_nopol"],
            nomor_wa=context.user_data.get("reg_wa"),
            jenis_mobil=context.user_data.get("reg_type"),
            tahun_mobil=context.user_data.get("reg_year"),
            alamat_client=context.user_data.get("reg_address"),
        )
        await query.edit_message_text(
            "✅ Kendaraan berhasil didaftarkan:\n\n" + format_vehicle(vehicle),
        )
    except (ConflictError, ValidationError) as e:
        await query.edit_message_text(f"❌ {e}")
    except Exception:
        logger.exception("Gagal menyimpan kendaraan")
        await query.edit_message_text("❌ Terjadi kesalahan saat menyimpan. Data tidak tersimpan.")
    finally:
        session.close()
    context.user_data.clear()
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Service record conversation
# ---------------------------------------------------------------------------
@require_auth
async def cmd_servis_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Nomor polisi kendaraan yang akan diservis?")
    return SVC_PLATE


@require_auth
async def svc_plate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    normalized = normalize_plate(update.message.text)
    session = _session()
    try:
        vehicle = VehicleService(session).find_vehicle_by_plate(normalized)
    finally:
        session.close()
    if vehicle is None:
        await update.message.reply_text(
            f"❌ Kendaraan dengan plat {normalized} belum terdaftar. Daftarkan dulu dengan /daftar."
        )
        return ConversationHandler.END
    context.user_data["svc_vehicle_id"] = vehicle.id
    context.user_data["svc_vehicle_nopol"] = vehicle.nopol
    await update.message.reply_text(
        "Pekerjaan/jasa (satu baris per pekerjaan):\n"
        "Format: `deskripsi|jumlah|harga`\n"
        "Contoh: `Pasang radiator|1|150000`\n"
        "Ketik `-` jika tidak ada.",
        parse_mode="Markdown",
    )
    return SVC_JOBS


@require_auth
async def svc_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text and text != "-":
        jobs = [
            {"deskripsi": name, "jumlah": qty, "harga": price}
            for name, qty, price in parse_item_lines(text)
        ]
        context.user_data["svc_jobs"] = jobs
    else:
        context.user_data["svc_jobs"] = []
    await update.message.reply_text(
        "Part (satu baris per part):\n"
        "Format: `nama_part|jumlah|harga_satuan`\n"
        "Contoh: `Radiator|1|850000`\n"
        "Ketik `-` jika tidak ada.",
        parse_mode="Markdown",
    )
    return SVC_PARTS


@require_auth
async def svc_parts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text and text != "-":
        parts = [
            {"nama_part": name, "jumlah": qty, "harga_satuan": price}
            for name, qty, price in parse_item_lines(text)
        ]
        context.user_data["svc_parts"] = parts
    else:
        context.user_data["svc_parts"] = []
    await update.message.reply_text(
        "Tanggal garansi s/d? (format YYYY-MM-DD, ketik '-' jika belum diketahui)"
    )
    return SVC_WARRANTY


@require_auth
async def svc_warranty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        garansi = parse_optional_date(update.message.text)
    except ValidationError as e:
        await update.message.reply_text(f"❌ {e} Ketik ulang:")
        return SVC_WARRANTY
    context.user_data["svc_garansi"] = garansi
    await update.message.reply_text("Catatan tambahan? (ketik '-' jika tidak ada)")
    return SVC_NOTES


@require_auth
async def svc_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["svc_catatan"] = None if (not text or text == "-") else text

    jobs = context.user_data.get("svc_jobs", [])
    parts = context.user_data.get("svc_parts", [])
    garansi = context.user_data.get("svc_garansi")
    lines = ["Konfirmasi servis:", f"🚗 Plat: {context.user_data.get('svc_vehicle_nopol')}"]
    lines.append("• Pekerjaan:")
    if jobs:
        for j in jobs:
            lines.append(f"  - {j['deskripsi']} (x{j['jumlah']}) @ {j['harga'] or '-'}")
    else:
        lines.append("  (tidak ada)")
    lines.append("• Part:")
    if parts:
        for p in parts:
            lines.append(f"  - {p['nama_part']} (x{p['jumlah']}) @ {p['harga_satuan'] or '-'}")
    else:
        lines.append("  (tidak ada)")
    lines.append(f"🛡️ Garansi s/d: {garansi.strftime('%d/%m/%Y') if garansi else 'belum diketahui'}")
    lines.append("Total dihitung otomatis saat penyimpanan.")

    session = _session()
    try:
        for warning in catalog_price_warnings(session, jobs, parts):
            lines.append(warning)
    finally:
        session.close()

    keyboard = [[
        InlineKeyboardButton("✅ Simpan", callback_data="svc_save"),
        InlineKeyboardButton("❌ Batal", callback_data="svc_cancel"),
    ]]
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(keyboard))
    return SVC_CONFIRM


@require_auth
async def confirm_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "svc_cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ Pencatatan servis dibatalkan.")
        return ConversationHandler.END
    session = _session()
    try:
        record = ServiceRecordService(session).add_service_record(
            context.user_data["svc_vehicle_id"],
            jobs=context.user_data.get("svc_jobs"),
            parts=context.user_data.get("svc_parts"),
            garansi_sampai=context.user_data.get("svc_garansi"),
            catatan=context.user_data.get("svc_catatan"),
        )
        await query.edit_message_text(
            "✅ Riwayat servis berhasil disimpan:\n\n" + format_service_record(record),
        )
    except (ConflictError, ValidationError) as e:
        await query.edit_message_text(f"❌ {e}")
    except Exception:
        logger.exception("Gagal menyimpan riwayat servis")
        await query.edit_message_text("❌ Terjadi kesalahan saat menyimpan. Data tidak tersimpan.")
    finally:
        session.close()
    context.user_data.clear()
    return ConversationHandler.END


@require_auth
async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Dibatalkan.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Conversation handler objects (registered by bot.application)
# ---------------------------------------------------------------------------
register_conv = ConversationHandler(
    entry_points=[CommandHandler("daftar", cmd_daftar_entry)],
    states={
        REG_NAME: [MessageHandler(FORM_TEXT_FILTER, reg_name)],
        REG_PLATE: [MessageHandler(FORM_TEXT_FILTER, reg_plate)],
        REG_WA: [MessageHandler(FORM_TEXT_FILTER, reg_wa)],
        REG_TYPE: [MessageHandler(FORM_TEXT_FILTER, reg_type)],
        REG_YEAR: [MessageHandler(FORM_TEXT_FILTER, reg_year)],
        REG_ADDRESS: [MessageHandler(FORM_TEXT_FILTER, reg_address)],
        REG_CONFIRM: [CallbackQueryHandler(confirm_register_callback, pattern="^reg_(save|cancel)$")],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_conversation),
        MessageHandler(CANCEL_FILTER, cancel_conversation),
    ],
)

service_conv = ConversationHandler(
    entry_points=[CommandHandler("servis", cmd_servis_entry)],
    states={
        SVC_PLATE: [MessageHandler(FORM_TEXT_FILTER, svc_plate)],
        SVC_JOBS: [MessageHandler(FORM_TEXT_FILTER, svc_jobs)],
        SVC_PARTS: [MessageHandler(FORM_TEXT_FILTER, svc_parts)],
        SVC_WARRANTY: [MessageHandler(FORM_TEXT_FILTER, svc_warranty)],
        SVC_NOTES: [MessageHandler(FORM_TEXT_FILTER, svc_notes)],
        SVC_CONFIRM: [CallbackQueryHandler(confirm_service_callback, pattern="^svc_(save|cancel)$")],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_conversation),
        MessageHandler(CANCEL_FILTER, cancel_conversation),
    ],
)




