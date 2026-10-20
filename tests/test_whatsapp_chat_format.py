"""Tests: WhatsApp chat format rules (WA-CS-CHAT-FORMAT-FIX-01)."""

import asyncio

from whatsapp.agent import (
    DB_UNAVAILABLE_REPLY,
    SAVE_FAILED_REPLY,
    WhatsAppAgent,
    build_system_prompt,
)
from whatsapp.services import SettingsService


SEPARATORS = ("---", "___", "***")


def _prompt(wa_session):
    return build_system_prompt(SettingsService(wa_session).get())


def test_prompt_has_whatsapp_format_rules(wa_session):
    p = _prompt(wa_session)
    assert "garis pemisah" in p
    assert "natural" in p
    assert "paragraf pendek" in p
    assert "bintang" in p


def test_prompt_still_has_safety_rules(wa_session):
    p = _prompt(wa_session)
    for needle in ("PRIORITAS", "Uppertank", "escalate_to_owner", "get_jasa_price", "save_memory"):
        assert needle in p


def test_greeting_has_no_separator(wa_session, session):
    s = SettingsService(wa_session).get()
    s.nama_bengkel = "Bengkel Jaya"
    wa_session.commit()
    reply = asyncio.run(WhatsAppAgent().reply("0812-1", "halo", wa_session, session))
    for sep in SEPARATORS:
        assert sep not in reply


def test_safe_replies_have_no_separator():
    for text in (DB_UNAVAILABLE_REPLY, SAVE_FAILED_REPLY):
        for sep in SEPARATORS:
            assert sep not in text


def test_reply_delay_still_5_seconds():
    from api.whatsapp_routes import WA_REPLY_DELAY_SECONDS, _reply_delay
    assert WA_REPLY_DELAY_SECONDS == 5
    assert _reply_delay() == 5
