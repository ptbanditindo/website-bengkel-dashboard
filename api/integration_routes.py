"""Integration settings endpoints: WhatsApp (Baileys), Telegram, AI providers."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.app import require_ui_access
from database.session import get_db
from sqlalchemy.orm import Session
from config import settings as settings_store
from config import testing as testing_mod
from whatsapp import baileys_client
from whatsapp.agent import WhatsAppAgent
from whatsapp.db import get_whatsapp_db
from whatsapp.normalize import normalize_wa_number
from whatsapp.services import ContactService

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
    logger.info("[debug-deepseek] inbound_received number=%s message_id=%s text_length=%d", wa_number, message_id, len(text))
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
    ContactService(wdb).record_message(contact.id, "ai", reply)
    wdb.commit()
    st = baileys_client.status()
    send_result = {"sent": False, "error": "bridge_not_connected"}
    if st.get("status") == "connected":
        send_result = baileys_client.send_message(wa_number, reply)
    logger.info("[debug-deepseek] outbound_result number=%s bridge_status=%s sent=%s error=%s", wa_number, st.get("status"), bool(send_result.get("sent")), send_result.get("error"))
    return {"processed": True, "reply_sent": bool(send_result.get("sent"))}
