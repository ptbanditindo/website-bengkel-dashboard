"""WhatsApp CS owner endpoints (authenticated via the existing bearer token)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.app import require_ui_access
from database.session import get_db
from services.exceptions import ServiceError
from whatsapp import baileys_client
from whatsapp.db import get_whatsapp_db
from whatsapp.models import WaArrivalPlan, WaCandidate, WaMessage, WaOwnerQuestion
from whatsapp.services import (
    ArrivalService,
    CandidateService,
    ContactService,
    QuestionService,
    SettingsService,
)

wa_router = APIRouter(prefix="/api/wa", tags=["whatsapp"])


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
        cs.record_message(contact.id, "owner", text)
        QuestionService(wdb).answer_pending_for_contact(contact.id, text)
        cs.set_takeover(contact.id)
        wdb.commit()
        send_result = {"sent": False, "error": "WhatsApp bridge tidak terhubung."}
        st = baileys_client.status()
        if st.get("status") == "connected":
            send_result = baileys_client.send_message(contact.wa_number, text)
        return {"sent": bool(send_result.get("sent")), "error": send_result.get("error"), "owner_takeover": True}
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
