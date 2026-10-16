"""WhatsApp CS business services (separate from main workshop services).

Cross-database reads (matching, price, stock) go through these restricted
functions only — never raw SQL from the AI. Write operations only touch the
WhatsApp DB, except ACC which uses the official VehicleService to create/link a
vehicle (never a service record, never stock/finance).
"""

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from database.models import HargaJasa, ServiceRecord, StockItem, Vehicle, normalize_plate
from services.exceptions import ConflictError, NotFoundError, ValidationError
from services.vehicle_service import VehicleService
from whatsapp import models
from whatsapp.normalize import normalize_wa_number


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContactService:
    def __init__(self, session: Session):
        self._s = session

    def get_or_create(self, wa_number: str) -> models.WaContact:
        n = normalize_wa_number(wa_number)
        if not n:
            raise ValidationError("Nomor WhatsApp tidak valid (kosong).")
        contact = self._s.scalar(select(models.WaContact).where(models.WaContact.wa_number == n))
        if contact is None:
            contact = models.WaContact(wa_number=n, registration_status=models.REG_MENUNGGU)
            self._s.add(contact)
            self._s.flush()
        return contact

    def get(self, contact_id: int) -> models.WaContact:
        c = self._s.get(models.WaContact, contact_id)
        if c is None:
            raise NotFoundError("Kontak WhatsApp tidak ditemukan.")
        return c

    def list(self, q: str = "", status: str = "") -> list[models.WaContact]:
        contacts = list(self._s.scalars(select(models.WaContact).order_by(models.WaContact.updated_at.desc())))
        q = (q or "").strip().lower()
        if q:
            contacts = [c for c in contacts if q in ((c.wa_number or "") + " " + (c.nama or "") + " " + (c.plat or "")).lower()]
        if status:
            contacts = [c for c in contacts if c.registration_status == status]
        return contacts

    def record_message(self, contact_id: int, sender: str, body: str, gateway_message_id: str | None = None):
        """Return (created: bool, message). Dedups by gateway_message_id."""
        if gateway_message_id:
            existing = self._s.scalar(select(models.WaMessage).where(models.WaMessage.gateway_message_id == gateway_message_id))
            if existing is not None:
                return False, existing
        msg = models.WaMessage(contact_id=contact_id, sender=sender, body=body, gateway_message_id=gateway_message_id)
        self._s.add(msg)
        self._s.flush()
        return True, msg

    def update_memory(self, contact_id: int, **fields) -> models.WaContact:
        c = self.get(contact_id)
        for k, v in fields.items():
            if hasattr(c, k):
                setattr(c, k, v)
        c.last_contact_at = _utcnow()
        return c

    def set_takeover(self, contact_id: int) -> models.WaContact:
        c = self.get(contact_id)
        c.owner_takeover_on = date.today()
        return c

    def is_taken_over(self, contact_id: int) -> bool:
        c = self.get(contact_id)
        return c.owner_takeover_on is not None and c.owner_takeover_on >= date.today()


class MatchingService:
    """Restricted cross-DB reads against the main workshop DB."""

    def __init__(self, main_session: Session):
        self._s = main_session

    def match_by_wa_number(self, wa_number: str) -> list[Vehicle]:
        n = normalize_wa_number(wa_number)
        if not n:
            return []
        candidates = self._s.scalars(select(Vehicle).where(Vehicle.nomor_wa.isnot(None))).all()
        return [v for v in candidates if normalize_wa_number(v.nomor_wa) == n]

    @staticmethod
    def public_vehicle(vehicle: Vehicle) -> dict:
        return {
            "id": vehicle.id,
            "nopol": vehicle.nopol,
            "nama_client": vehicle.nama_client,
            "jenis_mobil": vehicle.jenis_mobil,
            "tahun_mobil": vehicle.tahun_mobil,
        }

    def service_history(self, vehicle_id: int, wa_number: str) -> list[dict]:
        """Return non-financial service history, only if ownership matches."""
        vehicle = self._s.get(Vehicle, vehicle_id)
        if vehicle is None:
            raise NotFoundError("Kendaraan tidak ditemukan.")
        if normalize_wa_number(vehicle.nomor_wa or "") != normalize_wa_number(wa_number):
            raise ValidationError("Akses ditolak: nomor tidak cocok dengan kendaraan.")
        records = self._s.scalars(
            select(ServiceRecord)
            .where(ServiceRecord.vehicle_id == vehicle_id)
            .options(selectinload(ServiceRecord.jobs), selectinload(ServiceRecord.parts))
            .order_by(ServiceRecord.waktu_service.desc())
        ).all()
        return [
            {
                "waktu": r.waktu_service.strftime("%d/%m/%Y"),
                "pekerjaan": [j.deskripsi for j in r.jobs],
                "part": [p.nama_part for p in r.parts],
                "catatan": r.catatan,
            }
            for r in records
        ]


class PriceService:
    """Restricted public price/stock reads against the main DB."""

    def __init__(self, main_session: Session):
        self._s = main_session

    def check_stock(self, nama_part: str) -> str:
        items = self._s.scalars(select(StockItem).where(StockItem.nama.ilike(f"%{nama_part}%"))).all()
        if not items:
            return "tidak diketahui"
        if any(i.jumlah > 0 for i in items):
            return "tersedia"
        return "tidak tersedia (stok habis)"

    def part_price(self, nama_part: str):
        item = self._s.scalar(select(StockItem).where(StockItem.nama.ilike(f"%{nama_part}%")).limit(1))
        if item is None or item.harga_jual is None:
            return None
        return float(item.harga_jual)

    def jasa_price(self, nama_jasa: str):
        item = self._s.scalar(select(HargaJasa).where(HargaJasa.nama.ilike(f"%{nama_jasa}%")).limit(1))
        if item is None or item.keuntungan is None:
            return None
        return float(item.keuntungan)


class CandidateService:
    def __init__(self, wa_session: Session, main_session: Session):
        self._s = wa_session
        self._main = main_session

    def create(self, contact_id: int, nopol=None, nama=None, jenis_mobil=None, tahun_mobil=None) -> models.WaCandidate:
        c = models.WaCandidate(contact_id=contact_id, nopol=nopol, nama=nama, jenis_mobil=jenis_mobil, tahun_mobil=tahun_mobil, status=models.REG_MENUNGGU)
        self._s.add(c)
        self._s.flush()
        return c

    def list(self, status: str = "") -> list[models.WaCandidate]:
        stmt = select(models.WaCandidate).order_by(models.WaCandidate.created_at.desc())
        cands = list(self._s.scalars(stmt))
        if status:
            cands = [c for c in cands if c.status == status]
        return cands

    def get(self, candidate_id: int) -> models.WaCandidate:
        c = self._s.get(models.WaCandidate, candidate_id)
        if c is None:
            raise NotFoundError("Kandidat tidak ditemukan.")
        return c

    def approve(self, candidate_id: int, reviewed_by: str | None = None) -> models.WaCandidate:
        cand = self.get(candidate_id)
        if cand.status != models.REG_MENUNGGU:
            raise ConflictError("Kandidat sudah diproses.")
        nopol = normalize_plate(cand.nopol or "")
        if not nopol:
            raise ValidationError("Plat nomor wajib diisi sebelum ACC.")
        contact = self._s.get(models.WaContact, cand.contact_id)
        if contact is None:
            raise NotFoundError("Kontak WhatsApp tidak ditemukan.")
        try:
            vehicle_service = VehicleService(self._main)
            existing = vehicle_service.find_vehicle_by_plate(nopol)
            if existing is not None:
                vehicle_id = existing.id
            else:
                matches = [v for v in self._main.scalars(select(Vehicle).where(Vehicle.nomor_wa.isnot(None))).all() if normalize_wa_number(v.nomor_wa) == contact.wa_number]
                if matches:
                    raise ConflictError("Nomor WhatsApp sudah menempel pada kendaraan lain. Perlu tinjauan manual.")
                vehicle = vehicle_service.create_vehicle(
                    nama_client=cand.nama, nopol=nopol, nomor_wa=contact.wa_number,
                    jenis_mobil=cand.jenis_mobil, tahun_mobil=cand.tahun_mobil, commit=False,
                )
                vehicle_id = vehicle.id
            cand.status = models.REG_DISETUJUI
            cand.linked_vehicle_id = vehicle_id
            cand.reviewed_at = _utcnow()
            cand.reviewed_by = reviewed_by
            contact.linked_vehicle_id = vehicle_id
            contact.linked_vehicle_nopol = nopol
            contact.registration_status = models.REG_DISETUJUI
            self._main.commit()
            self._s.commit()
        except Exception:
            self._main.rollback()
            self._s.rollback()
            raise
        return cand

    def reject(self, candidate_id: int, alasan: str | None = None, reviewed_by: str | None = None) -> models.WaCandidate:
        cand = self.get(candidate_id)
        if cand.status != models.REG_MENUNGGU:
            raise ConflictError("Kandidat sudah diproses.")
        cand.status = models.REG_DITOLAK
        cand.alasan_tolak = alasan
        cand.reviewed_at = _utcnow()
        cand.reviewed_by = reviewed_by
        contact = self._s.get(models.WaContact, cand.contact_id)
        if contact is not None:
            contact.registration_status = models.REG_DITOLAK
        self._s.commit()
        return cand


class ArrivalService:
    def __init__(self, session: Session):
        self._s = session

    def create_plan(self, contact_id: int, rencana_hari=None, tanggal=None, waktu_perkiraan=None, catatan=None) -> models.WaArrivalPlan:
        p = models.WaArrivalPlan(contact_id=contact_id, rencana_hari=rencana_hari, tanggal=tanggal, waktu_perkiraan=waktu_perkiraan, status=models.PLAN_RENCANA, catatan=catatan)
        self._s.add(p)
        self._s.commit()
        return p

    def list(self) -> list[models.WaArrivalPlan]:
        return list(self._s.scalars(select(models.WaArrivalPlan).order_by(models.WaArrivalPlan.created_at.desc())))

    def set_status(self, plan_id: int, status: str) -> models.WaArrivalPlan:
        p = self._s.get(models.WaArrivalPlan, plan_id)
        if p is None:
            raise NotFoundError("Rencana kedatangan tidak ditemukan.")
        if status not in (models.PLAN_RENCANA, models.PLAN_DATANG, models.PLAN_TIDAK_DATANG, models.PLAN_BATAL):
            raise ValidationError("Status rencana kedatangan tidak valid.")
        p.status = status
        self._s.commit()
        return p


class QuestionService:
    def __init__(self, session: Session):
        self._s = session

    def create(self, contact_id: int, wa_number: str, pesan: str, alasan: str | None = None) -> models.WaOwnerQuestion:
        q = models.WaOwnerQuestion(contact_id=contact_id, wa_number=wa_number, pesan=pesan, alasan=alasan, status=models.QUESTION_MENUNGGU)
        self._s.add(q)
        self._s.commit()
        return q

    def list(self, status: str = "") -> list[models.WaOwnerQuestion]:
        stmt = select(models.WaOwnerQuestion).order_by(models.WaOwnerQuestion.created_at.desc())
        qs = list(self._s.scalars(stmt))
        if status:
            qs = [q for q in qs if q.status == status]
        return qs

    def answer(self, question_id: int, jawaban: str) -> models.WaOwnerQuestion:
        q = self._s.get(models.WaOwnerQuestion, question_id)
        if q is None:
            raise NotFoundError("Pertanyaan tidak ditemukan.")
        q.jawaban_owner = jawaban
        q.status = models.QUESTION_DIJAWAB
        self._s.commit()
        return q

    def close(self, question_id: int) -> models.WaOwnerQuestion:
        q = self._s.get(models.WaOwnerQuestion, question_id)
        if q is None:
            raise NotFoundError("Pertanyaan tidak ditemukan.")
        q.status = models.QUESTION_DITUTUP
        self._s.commit()
        return q

    def answer_pending_for_contact(self, contact_id: int, jawaban: str) -> int:
        qs = [q for q in self.list(models.QUESTION_MENUNGGU) if q.contact_id == contact_id]
        for q in qs:
            q.jawaban_owner = jawaban
            q.status = models.QUESTION_DIJAWAB
        if qs:
            self._s.commit()
        return len(qs)


SETTINGS_ALLOWED = {"nama_bengkel", "alamat", "jam_operasional", "maps_link", "agent_prompt", "default_delay_seconds", "redirect_enabled"}


class SettingsService:
    def __init__(self, session: Session):
        self._s = session

    def get(self) -> models.WaAgentSettings:
        s = self._s.get(models.WaAgentSettings, 1)
        if s is None:
            s = models.WaAgentSettings(id=1, default_delay_seconds=60, redirect_enabled=1)
            self._s.add(s)
            self._s.commit()
        return s

    def update(self, **fields) -> models.WaAgentSettings:
        s = self.get()
        for k, v in fields.items():
            if k in SETTINGS_ALLOWED and hasattr(s, k):
                setattr(s, k, v)
        self._s.commit()
        return s
