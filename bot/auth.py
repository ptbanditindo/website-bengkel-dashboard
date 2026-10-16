"""Authorization helpers for the Telegram bot."""

import os
from functools import wraps


def is_authorized(user_id) -> bool:
    """Return True when the given Telegram user id is authorized."""
    ids = [part.strip() for part in os.getenv("AUTHORIZED_USER_ID", "").split(",")]
    return str(user_id) in ids


async def _deny(update) -> None:
    """Best-effort reply for unauthorized users (never raises)."""
    message = "⛔ Anda tidak memiliki akses untuk menggunakan bot ini."
    try:
        if getattr(update, "callback_query", None):
            await update.callback_query.answer(message, show_alert=True)
        elif getattr(update, "message", None):
            await update.message.reply_text(message)
    except Exception:
        pass


def require_auth(handler):
    """Decorator blocking unauthorized users before a handler runs.

    Unauthorized users receive a deny message and the handler is never invoked
    (for a ConversationHandler state, returning ``None`` keeps them in place).
    """

    @wraps(handler)
    async def wrapper(update, context, *args, **kwargs):
        user = getattr(update, "effective_user", None)
        if user is None or not is_authorized(user.id):
            await _deny(update)
            return None
        return await handler(update, context, *args, **kwargs)

    return wrapper
