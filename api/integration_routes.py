"""Integration settings endpoints: WhatsApp (Baileys), Telegram, AI providers."""

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
        return {"processed": False}
    contact = ContactService(wdb).get_or_create(wa_number)
    created, _ = ContactService(wdb).record_message(contact.id, "customer", text, gateway_message_id=message_id)
    if not created:
        return {"processed": False, "duplicate": True}
    if ContactService(wdb).is_taken_over(contact.id):
        wdb.commit()
        return {"processed": True, "ai_skipped": True, "reason": "owner_takeover"}
    agent = WhatsAppAgent()
    reply = await agent.reply(wa_number, text, wdb, db)
    ContactService(wdb).record_message(contact.id, "ai", reply)
    wdb.commit()
    st = baileys_client.status()
    sent = False
    if st.get("status") == "connected":
        sent = bool(baileys_client.send_message(wa_number, reply).get("sent"))
    return {"processed": True, "reply_sent": sent}
