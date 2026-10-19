"""WhatsApp endpoints (owner dashboard + Baileys gateway).

All WhatsApp routing is grouped here:
- ``wa_router`` — owner dashboard (CS management), bearer ``UI_ACCESS_TOKEN``.
- ``wa_gateway_router`` — Baileys gateway control + inbound webhook.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api.auth import require_ui_access
from config import settings as settings_store
from database.session import get_db
from services.exceptions import ServiceError
from whatsapp import baileys_client
from whatsapp.agent import WhatsAppAgent
from whatsapp.db import get_whatsapp_db
from whatsapp.models import WaArrivalPlan, WaCandidate, WaMessage, WaOwnerQuestion
from whatsapp.normalize import normalize_wa_number
from whatsapp.services import (
    ArrivalService,
    CandidateService,
    ContactService,
    QuestionService,
    SettingsService,
    send_status_of,
)

logger = logging.getLogger(__name__)

wa_router = APIRouter(prefix="/api/wa", tags=["whatsapp"])
wa_gateway_router = APIRouter(prefix="/api/integrations/whatsapp", tags=["whatsapp-gateway"])


class RejectBody(BaseModel):
    alasan: str | None = None


class AnswerBody(BaseModel):
    jawaban: str


class ReplyBody(BaseModel):
    text: str


class StatusBody(BaseModel):
    status: str


class SettingsBody(BaseModel):
    nama_bengkel: str | None = None
    alamat: str | None = None
    jam_operasional: str | None = None
    maps_link: str | None = None
    agent_prompt: str | None = None
    default_delay_seconds: int | None = None
    redirect_enabled: int | None = None


class PhoneBody(BaseModel):
    phone: str = ""


def _contact_dict(c):
    return {
        "id": c.id, "wa_number": c.wa_number, "nama": c.nama, "plat": c.plat,
        "jenis_mobil": c.jenis_mobil, "tahun_mobil": c.tahun_mobil,
        "issue_summary": c.issue_summary, "context_summary": c.context_summary,
        "registration_status": c.registration_status, "arrival_status": c.arrival_status,
        "linked_vehicle_id": c.linked_vehicle_id, "linked_vehicle_nopol": c.linked_vehicle_nopol,
        "delay_seconds": c.delay_seconds,
        "owner_takeover_on": c.owner_takeover_on.isoformat() if c.owner_takeover_on else None,
        "last_contact_at": c.last_contact_at.isoformat() if c.last_contact_at else None,
    }


def _candidate_dict(c):
    return {
        "id": c.id, "contact_id": c.contact_id, "nopol": c.nopol, "nama": c.nama,
        "jenis_mobil": c.jenis_mobil, "tahun_mobil": c.tahun_mobil, "status": c.status,
        "alasan_tolak": c.alasan_tolak, "linked_vehicle_id": c.linked_vehicle_id,
    }


def _plan_dict(p):
    return {
        "id": p.id, "contact_id": p.contact_id, "rencana_hari": p.rencana_hari,
        "tanggal": p.tanggal.isoformat() if p.tanggal else None,
        "waktu_perkiraan": p.waktu_perkiraan, "status": p.status, "catatan": p.catatan,
    }


def _question_dict(q):
    return {
        "id": q.id, "contact_id": q.contact_id, "wa_number": q.wa_number,
        "pesan": q.pesan, "alasan": q.alasan, "status": q.status, "jawaban_owner": q.jawaban_owner,
    }


def _message_dict(m):
    return {"id": m.id, "sender": m.sender, "body": m.body, "created_at": m.created_at.isoformat() if m.created_at else None}


def _settings_dict(s):
    return {
        "nama_bengkel": s.nama_bengkel, "alamat": s.alamat, "jam_operasional": s.jam_operasional,
        "maps_link": s.maps_link, "agent_prompt": s.agent_prompt,
        "default_delay_seconds": s.default_delay_seconds, "redirect_enabled": s.redirect_enabled,
    }


@wa_router.get("/contacts")
def list_contacts(q: str = "", status: str = "", wdb: Session = Depends(get_whatsapp_db), _: None = Depends(require_ui_access)):
    return [_contact_dict(c) for c in ContactService(wdb).list(q, status)]


@wa_router.get("/contacts/{contact_id}")
def get_contact(contact_id: int, wdb: Session = Depends(get_whatsapp_db), _: None = Depends(require_ui_access)):
    c = ContactService(wdb).get(contact_id)
    messages = list(wdb.query(WaMessage).filter(WaMessage.contact_id == contact_id).order_by(WaMessage.created_at.asc()))
    candidates = list(wdb.query(WaCandidate).filter(WaCandidate.contact_id == contact_id).order_by(WaCandidate.created_at.desc()))
    plans = list(wdb.query(WaArrivalPlan).filter(WaArrivalPlan.contact_id == contact_id).order_by(WaArrivalPlan.created_at.desc()))
    questions = list(wdb.query(WaOwnerQuestion).filter(WaOwnerQuestion.contact_id == contact_id).order_by(WaOwnerQuestion.created_at.desc()))
    return {
        "contact": _contact_dict(c),
        "messages": [_message_dict(m) for m in messages],
        "candidates": [_candidate_dict(x) for x in candidates],
        "plans": [_plan_dict(x) for x in plans],
        "questions": [_question_dict(x) for x in questions],
    }


@wa_router.get("/candidates")
def list_candidates(status: str = "", wdb: Session = Depends(get_whatsapp_db), db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    return [_candidate_dict(c) for c in CandidateService(wdb, db).list(status)]


@wa_router.post("/candidates/{candidate_id}/approve")
def approve_candidate(candidate_id: int, wdb: Session = Depends(get_whatsapp_db), db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    try:
        return _candidate_dict(CandidateService(wdb, db).approve(candidate_id))
    except ServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@wa_router.post("/candidates/{candidate_id}/reject")
def reject_candidate(candidate_id: int, body: RejectBody, wdb: Session = Depends(get_whatsapp_db), db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    try:
        return _candidate_dict(CandidateService(wdb, db).reject(candidate_id, body.alasan))
    except ServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@wa_router.get("/arrivals")
def list_arrivals(wdb: Session = Depends(get_whatsapp_db), _: None = Depends(require_ui_access)):
    return [_plan_dict(p) for p in ArrivalService(wdb).list()]


@wa_router.post("/arrivals/{plan_id}/status")
def set_arrival_status(plan_id: int, body: StatusBody, wdb: Session = Depends(get_whatsapp_db), _: None = Depends(require_ui_access)):
    try:
        return _plan_dict(ArrivalService(wdb).set_status(plan_id, body.status))
    except ServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@wa_router.get("/questions")
def list_questions(status: str = "", wdb: Session = Depends(get_whatsapp_db), _: None = Depends(require_ui_access)):
    return [_question_dict(q) for q in QuestionService(wdb).list(status)]


@wa_router.post("/questions/{question_id}/answer")
def answer_question(question_id: int, body: AnswerBody, wdb: Session = Depends(get_whatsapp_db), _: None = Depends(require_ui_access)):
    try:
        return _question_dict(QuestionService(wdb).answer(question_id, body.jawaban))
    except ServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@wa_router.post("/questions/{question_id}/close")
def close_question(question_id: int, wdb: Session = Depends(get_whatsapp_db), _: None = Depends(require_ui_access)):
    try:
        return _question_dict(QuestionService(wdb).close(question_id))
    except ServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@wa_router.post("/contacts/{contact_id}/reply")
def reply_contact(contact_id: int, body: ReplyBody, wdb: Session = Depends(get_whatsapp_db), _: None = Depends(require_ui_access)):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Pesan kosong.")
    try:
        cs = ContactService(wdb)
        contact = cs.get(contact_id)
        _, owner_msg = cs.record_message(contact.id, "owner", text)
        QuestionService(wdb).answer_pending_for_contact(contact.id, text)
        cs.set_takeover(contact.id)
        wdb.commit()
        send_result = {"sent": False, "error": "WhatsApp bridge tidak terhubung."}
        st = baileys_client.status()
        if st.get("status") == "connected":
            send_result = baileys_client.send_message(contact.wa_number, text)
        status = send_status_of(send_result)
        cs.mark_send_status(owner_msg.id, status)
        wdb.commit()
        return {"sent": bool(send_result.get("sent")), "error": send_result.get("error"), "owner_takeover": True, "send_status": status}
    except ServiceError as e:
        raise HTTPException(status_code=400, detail=str(e))


@wa_router.get("/settings")
def get_settings(wdb: Session = Depends(get_whatsapp_db), _: None = Depends(require_ui_access)):
    return _settings_dict(SettingsService(wdb).get())


@wa_router.put("/settings")
def update_settings(body: SettingsBody, wdb: Session = Depends(get_whatsapp_db), _: None = Depends(require_ui_access)):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    return _settings_dict(SettingsService(wdb).update(**fields))


@wa_router.get("/gateway/status")
def gateway_status(_: None = Depends(require_ui_access)):
    st = baileys_client.status()
    return {
        "connected": st.get("status") == "connected",
        "provider": st.get("provider", "knightbot-md"),
        "detail": st.get("error") or "",
        "authedNumber": st.get("authedNumber"),
    }


# ---------------------------------------------------------------------------
# Baileys gateway control (owner dashboard, bearer UI_ACCESS_TOKEN)
# ---------------------------------------------------------------------------

@wa_gateway_router.get("/status")
def whatsapp_status(_: None = Depends(require_ui_access)):
    return baileys_client.status()


@wa_gateway_router.post("/qr/start")
def whatsapp_qr_start(_: None = Depends(require_ui_access)):
    return baileys_client.start_qr()


@wa_gateway_router.post("/pairing/request")
def whatsapp_pairing(body: PhoneBody, _: None = Depends(require_ui_access)):
    phone = normalize_wa_number(body.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Nomor tidak valid.")
    return baileys_client.request_pairing(phone)


@wa_gateway_router.post("/logout")
def whatsapp_logout(_: None = Depends(require_ui_access)):
    return baileys_client.logout()


# ---------------------------------------------------------------------------
# Inbound webhook from the Baileys bridge (internal auth, not UI token)
# ---------------------------------------------------------------------------

WA_REPLY_DELAY_SECONDS = 5


def _reply_delay() -> int:
    """Effective reply delay in seconds (fixed at 5s; see WA-DELAY-05)."""
    return max(0, min(WA_REPLY_DELAY_SECONDS, 120))


@wa_gateway_router.post("/inbound")
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
