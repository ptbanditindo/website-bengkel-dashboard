"""Integration settings endpoints: WhatsApp (Baileys), Telegram, AI providers."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.app import require_ui_access
from config import settings as settings_store
from config import testing as testing_mod
from database.session import get_db
from whatsapp import baileys_client
from whatsapp.agent import WhatsAppAgent
from whatsapp.db import get_whatsapp_db
from whatsapp.normalize import normalize_wa_number
from whatsapp.services import ContactService, send_status_of

logger = logging.getLogger(__name__)

int_router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class ValueBody(BaseModel):
    value: str = ""


class TokenBody(BaseModel):
    token: str = ""


class PhoneBody(BaseModel):
    phone: str = ""


@int_router.get("/status")
def get_status(_: None = Depends(require_ui_access)):
    return {"providers": settings_store.status(), "whatsapp": baileys_client.status()}


# ---- Telegram ----
@int_router.post("/telegram/save")
def telegram_save(body: TokenBody, _: None = Depends(require_ui_access)):
    result = testing_mod.test_telegram_token(body.token)
    if not result.get("valid"):
        raise HTTPException(status_code=400, detail=result.get("error", "Token tidak valid."))
    settings_store.set("telegram_bot_token", body.token)
    return {"saved": True, "username": result.get("username"), "needs_restart": True}


@int_router.post("/telegram/test")
def telegram_test(body: TokenBody, _: None = Depends(require_ui_access)):
    return testing_mod.test_telegram_token(body.token)


@int_router.post("/telegram/delete")
def telegram_delete(_: None = Depends(require_ui_access)):
    settings_store.delete("telegram_bot_token")
    return {"deleted": True}


# ---- DeepSeek ----
@int_router.post("/deepseek/save")
def deepseek_save(body: ValueBody, _: None = Depends(require_ui_access)):
    settings_store.set("deepseek_api_key", body.value)
    return {"saved": True, "needs_restart": True}


@int_router.post("/deepseek/test")
def deepseek_test(body: ValueBody, _: None = Depends(require_ui_access)):
    return testing_mod.test_deepseek_key(body.value)


@int_router.post("/deepseek/delete")
def deepseek_delete(_: None = Depends(require_ui_access)):
    settings_store.delete("deepseek_api_key")
    return {"deleted": True}


# ---- Gemini ----
@int_router.post("/gemini/save")
def gemini_save(body: ValueBody, _: None = Depends(require_ui_access)):
    settings_store.set("gemini_api_key", body.value)
    return {"saved": True, "needs_restart": True}


@int_router.post("/gemini/test")
def gemini_test(body: ValueBody, _: None = Depends(require_ui_access)):
    return testing_mod.test_gemini_key(body.value)


@int_router.post("/gemini/delete")
def gemini_delete(_: None = Depends(require_ui_access)):
    settings_store.delete("gemini_api_key")
    return {"deleted": True}


# ---- WhatsApp (Baileys) ----
@int_router.get("/whatsapp/status")
def whatsapp_status(_: None = Depends(require_ui_access)):
    return baileys_client.status()


@int_router.post("/whatsapp/qr/start")
def whatsapp_qr_start(_: None = Depends(require_ui_access)):
    return baileys_client.start_qr()


@int_router.post("/whatsapp/pairing/request")
def whatsapp_pairing(body: PhoneBody, _: None = Depends(require_ui_access)):
    phone = normalize_wa_number(body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Nomor tidak valid.")
    return baileys_client.request_pairing(phone)


@int_router.post("/whatsapp/logout")
def whatsapp_logout(_: None = Depends(require_ui_access)):
    return baileys_client.logout()


# ---- Inbound webhook from the Baileys bridge (internal auth) ----
WA_REPLY_DELAY_SECONDS = 5


def _reply_delay() -> int:
    """Effective reply delay in seconds (fixed at 5s; see WA-DELAY-05)."""
    return max(0, min(WA_REPLY_DELAY_SECONDS, 120))


@int_router.post("/whatsapp/inbound")
async def whatsapp_inbound(payload: dict, request: Request, wdb=Depends(get_whatsapp_db), db: Session = Depends(get_db)):
    auth = request.headers.get("authorization", "")
    if auth != "Bearer " + settings_store.get_internal_token():
        raise HTTPException(status_code=401, detail="unauthorized")
    wa_number = normalize_wa_number(payload.get("from", ""))
    message_id = payload.get("message_id")
    text = (payload.get("text") or "").strip()
    if not wa_number or not text:
        logger.warning("[debug-deepseek] inbound_rejected has_number=%s text_length=%d", bool(wa_number), len(text))
        return {"processed": False}
    from_me = bool(payload.get("from_me"))
    if from_me:
        # Owner replied manually from the bot's own WhatsApp number.
        try:
            contact = ContactService(wdb).get_or_create(wa_number)
            ContactService(wdb).record_message(contact.id, "owner", text, gateway_message_id=message_id)
            ContactService(wdb).set_takeover(contact.id)
            wdb.commit()
        except SQLAlchemyError as e:
            try:
                wdb.rollback()
            except Exception:  # noqa: BLE001 — cleanup only
                pass
            logger.error("[debug-deepseek] whatsapp_db_unavailable from_me error=%s", e)
            return JSONResponse(status_code=503, content={"processed": False, "error": "database_unavailable"})
        logger.info("[debug-deepseek] owner_takeover_set number=%s", wa_number)
        return {"processed": True, "owner_takeover": True}
    logger.info("[debug-deepseek] inbound_received number=%s message_id=%s text_length=%d", wa_number, message_id, len(text))
    try:
        contact = ContactService(wdb).get_or_create(wa_number)
        created, _ = ContactService(wdb).record_message(contact.id, "customer", text, gateway_message_id=message_id)
        if not created:
            return {"processed": False, "duplicate": True}
        takeover_active = ContactService(wdb).is_taken_over(contact.id)
        logger.info(
            "[debug-deepseek] takeover_check contact_id=%s number=%s owner_takeover_on=%s active=%s",
            contact.id,
            wa_number,
            contact.owner_takeover_on,
            takeover_active,
        )
        if takeover_active:
            wdb.commit()
            return {"processed": True, "ai_skipped": True, "reason": "owner_takeover"}
        agent = WhatsAppAgent()
        reply = await agent.reply(wa_number, text, wdb, db)
        logger.info("[debug-deepseek] reply_ready number=%s reply_length=%d", wa_number, len(reply or ""))
        _, ai_msg = ContactService(wdb).record_message(contact.id, "ai", reply)
        wdb.commit()
        st = baileys_client.status()
        send_result = {"sent": False, "error": "bridge_not_connected"}
        if st.get("status") == "connected":
            delay = _reply_delay()
            if delay > 0:
                await asyncio.sleep(delay)
            send_result = baileys_client.send_message(wa_number, reply)
        status = send_status_of(send_result)
        ContactService(wdb).mark_send_status(ai_msg.id, status)
        wdb.commit()
        logger.info(
            "[debug-deepseek] outbound_result number=%s bridge_status=%s sent=%s status=%s error=%s",
            wa_number, st.get("status"), bool(send_result.get("sent")), status, send_result.get("error"),
        )
        return {"processed": True, "reply_sent": bool(send_result.get("sent")), "send_status": status}
    except SQLAlchemyError as e:
        try:
            wdb.rollback()
        except Exception:  # noqa: BLE001 — cleanup only, never mask the failure
            pass
        logger.error("[debug-deepseek] whatsapp_db_unavailable error=%s", e)
        return JSONResponse(status_code=503, content={"processed": False, "error": "database_unavailable"})
