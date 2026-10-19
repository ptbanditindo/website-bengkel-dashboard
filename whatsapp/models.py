"""WhatsApp CS ORM models on a SEPARATE declarative base.

This schema lives in data/whatsapp_cs.db and never touches the main
workshop.db schema. No financial/internal columns exist here.
"""

from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WhatsAppBase(DeclarativeBase):
    pass


REG_MENUNGGU = "MENUNGGU_REVIEW"
REG_DISETUJUI = "DISETUJUI"
REG_DITOLAK = "DITOLAK"

ARR_KOSONG = "KOSONG"
ARR_MENUNGGU = "MENUNGGU_KEDATANGAN"
ARR_DIJADWALKAN = "DIJADWALKAN"
ARR_DATANG = "DATANG"
ARR_TIDAK_DATANG = "TIDAK_DATANG"

QUESTION_MENUNGGU = "MENUNGGU"
QUESTION_DIJAWAB = "DIJAWAB"
QUESTION_DITUTUP = "DITUTUP"

PLAN_RENCANA = "RENCANA"
PLAN_DATANG = "DATANG"
PLAN_TIDAK_DATANG = "TIDAK_DATANG"
PLAN_BATAL = "BATAL"


class WaContact(WhatsAppBase):
    __tablename__ = "wa_contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wa_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    nama: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plat: Mapped[str | None] = mapped_column(String(32), nullable=True)
    jenis_mobil: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tahun_mobil: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issue_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    registration_status: Mapped[str] = mapped_column(String(32), nullable=False, default=REG_MENUNGGU)
    arrival_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    linked_vehicle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linked_vehicle_nopol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    owner_takeover_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class WaMessage(WhatsAppBase):
    __tablename__ = "wa_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("wa_contacts.id"), nullable=False, index=True)
    sender: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    gateway_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    send_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class WaCandidate(WhatsAppBase):
    __tablename__ = "wa_candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("wa_contacts.id"), nullable=False, index=True)
    nopol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    nama: Mapped[str | None] = mapped_column(String(255), nullable=True)
    jenis_mobil: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tahun_mobil: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=REG_MENUNGGU, index=True)
    alasan_tolak: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_vehicle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class WaArrivalPlan(WhatsAppBase):
    __tablename__ = "wa_arrival_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("wa_contacts.id"), nullable=False, index=True)
    rencana_hari: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tanggal: Mapped[date | None] = mapped_column(Date, nullable=True)
    waktu_perkiraan: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=PLAN_RENCANA, index=True)
    catatan: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class WaOwnerQuestion(WhatsAppBase):
    __tablename__ = "wa_owner_questions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("wa_contacts.id"), nullable=False, index=True)
    wa_number: Mapped[str] = mapped_column(String(64), nullable=False)
    pesan: Mapped[str] = mapped_column(Text, nullable=False)
    alasan: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=QUESTION_MENUNGGU, index=True)
    jawaban_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class WaAgentSettings(WhatsAppBase):
    __tablename__ = "wa_agent_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nama_bengkel: Mapped[str | None] = mapped_column(Text, nullable=True)
    alamat: Mapped[str | None] = mapped_column(Text, nullable=True)
    jam_operasional: Mapped[str | None] = mapped_column(Text, nullable=True)
    maps_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    redirect_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
