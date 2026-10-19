"""Bot application factory and error handling."""

import logging
import os
from pathlib import Path

import telegram.error
from telegram import BotCommand
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)

from bot.ai_handlers import (
    ai_cancel_callback,
    ai_confirm_callback,
    ai_message_handler,
    ai_photo_handler,
)
from bot.handlers import (
    cancel_callback,
    cmd_cari,
    cmd_garansi,
    cmd_hapus,
    cmd_help,
    cmd_klaim,
    cmd_me,
    cmd_riwayat,
    cmd_start,
    confirm_delete_callback,
    confirm_klaim_callback,
    register_conv,
    select_klaim_callback,
    service_conv,
)
from database.session import init_db

logger = logging.getLogger(__name__)


def _telegram_token() -> str:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN tidak ditemukan di environment variables.")
    return token


def build_application() -> Application:
    """Build and configure the telegram bot application."""
    init_db()  # non-destructive: ensures data dir + tables exist

    persistence_file = os.getenv("BOT_DATA_FILE", "./data/bot_data.pickle")
    Path(persistence_file).parent.mkdir(parents=True, exist_ok=True)
    persistence = PicklePersistence(filepath=persistence_file)

    application = (
        Application.builder().token(_telegram_token()).persistence(persistence).build()
    )

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("me", cmd_me))
    application.add_handler(CommandHandler("cari", cmd_cari))
    application.add_handler(CommandHandler("riwayat", cmd_riwayat))
    application.add_handler(CommandHandler("garansi", cmd_garansi))
    application.add_handler(CommandHandler("klaim", cmd_klaim))
    application.add_handler(CommandHandler("hapus", cmd_hapus))

    application.add_handler(register_conv)
    application.add_handler(service_conv)

    application.add_handler(CallbackQueryHandler(select_klaim_callback, pattern="^klaim_"))
    application.add_handler(CallbackQueryHandler(confirm_klaim_callback, pattern="^confirm_klaim_"))
    application.add_handler(CallbackQueryHandler(confirm_delete_callback, pattern="^confirm_delete_"))
    application.add_handler(CallbackQueryHandler(cancel_callback, pattern="^(cancel_klaim|cancel_delete)$"))

    # AI-driven handlers (AI chat + vision + confirmation)
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, ai_photo_handler))
    application.add_handler(CallbackQueryHandler(ai_confirm_callback, pattern="^ai_confirm_"))
    application.add_handler(CallbackQueryHandler(ai_cancel_callback, pattern="^ai_cancel_"))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, ai_message_handler)
    )

    application.add_error_handler(error_handler)

    async def post_init(app: Application) -> None:
        commands = [
            BotCommand("start", "Menu utama"),
            BotCommand("daftar", "Daftarkan kendaraan baru"),
            BotCommand("servis", "Catat riwayat servis"),
            BotCommand("cari", "Cari kendaraan berdasarkan plat"),
            BotCommand("riwayat", "Lihat riwayat servis"),
            BotCommand("garansi", "Lihat status garansi"),
            BotCommand("klaim", "Ubah status klaim garansi"),
            BotCommand("hapus", "Hapus kendaraan"),
            BotCommand("help", "Bantuan"),
        ]
        await app.bot.set_my_commands(commands)

    application.post_init = post_init
    return application


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

    if isinstance(context.error, telegram.error.Conflict):
        logger.error("Bot conflict detected - another instance may be running.")
        return
    if isinstance(context.error, telegram.error.NetworkError):
        logger.error("Network error (temporary).")
        return


def run() -> None:
    """Build and run the bot (blocking)."""
    application = build_application()
    application.run_polling(drop_pending_updates=True)
