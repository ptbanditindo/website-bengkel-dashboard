"""Reporting / aggregation queries for the workshop archive.

All figures come from the actual database and are computed here in Python (or
via ORM aggregation) — never by the model. Money uses ``Decimal``. Unknown
(``NULL``) totals are never silently converted to zero: an aggregate that mixes
known and unknown totals reports ``None`` so it is shown as "belum diketahui".
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from database.models import ServiceJob, ServicePart, ServiceRecord, StockItem, Vehicle
from services.pricing import to_decimal


class ReportingService:
    """Read-only aggregations over vehicles and service records."""

    def __init__(self, session: Session):
        self._session = session

    def count_vehicles(self) -> int:
        return int(self._session.scalar(func.count(Vehicle.id)) or 0)

    def count_service_records(self) -> int:
        return int(self._session.scalar(func.count(ServiceRecord.id)) or 0)

    def service_totals(self, start=None, end=None) -> dict:
        """Count and total of service records (optionally in a date range).

        ``total_servis`` is ``None`` when any counted record has an unknown
        total (so a partial sum is never presented as a real value).
        """
        records = self._session.query(ServiceRecord).all()
        in_range = []
        for r in records:
            if start is not None and r.waktu_service < start:
                continue
            if end is not None and r.waktu_service >= end:
                continue
            in_range.append(r)

        total = Decimal("0")
        has_unknown = False
        for r in in_range:
            if r.total_servis is None:
                has_unknown = True
            else:
                total += r.total_servis

        return {
            "jumlah_servis": len(in_range),
            "jumlah_tercatat": sum(1 for r in in_range if r.total_servis is not None),
            "total_servis": None if has_unknown else to_decimal(total),
        }

    def profit_summary(self, start=None, end=None) -> dict:
        """Net profit from labour (biaya_jasa) and parts (subtotal - modal).

        Returns ``None`` for a component when any record/part in range has an
        unknown value for that component (never presents a partial sum).
        """
        jasa = Decimal("0")
        barang = Decimal("0")
        modal_barang = Decimal("0")
        omset_barang = Decimal("0")
        has_unknown_jasa = False
        has_unknown_barang = False
        has_unknown_modal = False
        has_unknown_omset = False
        for r in self._session.query(ServiceRecord).options(
            selectinload(ServiceRecord.parts), selectinload(ServiceRecord.jobs)
        ).all():
            if start is not None and r.waktu_service < start:
                continue
            if end is not None and r.waktu_service >= end:
                continue
            if r.biaya_jasa is None:
                if r.jobs:
                    has_unknown_jasa = True
            else:
                jasa += r.biaya_jasa
            for p in r.parts:
                modal = None
                if p.stock_item_id is not None:
                    stock = self._session.get(StockItem, p.stock_item_id)
                    if stock is not None and stock.harga_modal is not None:
                        modal = stock.harga_modal * p.jumlah
                if p.subtotal is None:
                    has_unknown_omset = True
                else:
                    omset_barang += p.subtotal
                if modal is None:
                    has_unknown_modal = True
                else:
                    modal_barang += modal
                if p.subtotal is None or modal is None:
                    has_unknown_barang = True
                else:
                    barang += (p.subtotal - modal)
        return {
            "keuntungan_jasa": None if has_unknown_jasa else to_decimal(jasa),
            "keuntungan_barang": None if has_unknown_barang else to_decimal(barang),
            "modal_barang": None if has_unknown_modal else to_decimal(modal_barang),
            "omset_barang": None if has_unknown_omset else to_decimal(omset_barang),
        }

    def period_summary(self, year=None) -> list[dict]:
        """Recap of service count and value per month (optionally one year)."""
        buckets: dict[str, dict] = {}
        for r in self._session.query(ServiceRecord).order_by(ServiceRecord.waktu_service).all():
            if year is not None and r.waktu_service.year != year:
                continue
            key = f"{r.waktu_service.year:04d}-{r.waktu_service.month:02d}"
            b = buckets.setdefault(
                key, {"periode": key, "jumlah_servis": 0, "total_servis": Decimal("0"), "_unknown": False}
            )
            b["jumlah_servis"] += 1
            if r.total_servis is None:
                b["_unknown"] = True
            else:
                b["total_servis"] += r.total_servis

        result = []
        for b in buckets.values():
            result.append(
                {
                    "periode": b["periode"],
                    "jumlah_servis": b["jumlah_servis"],
                    "total_servis": None if b["_unknown"] else to_decimal(b["total_servis"]),
                }
            )
        return result

    def top_jobs(self, limit: int = 5) -> list[dict]:
        rows = (
            self._session.query(
                ServiceJob.deskripsi, func.count(ServiceJob.id).label("jumlah")
            )
            .group_by(ServiceJob.deskripsi)
            .order_by(func.count(ServiceJob.id).desc(), ServiceJob.deskripsi.asc())
            .limit(limit)
            .all()
        )
        return [{"deskripsi": deskripsi, "jumlah": jumlah} for deskripsi, jumlah in rows]

    def part_usage(self) -> list[dict]:
        rows = (
            self._session.query(
                ServicePart.nama_part,
                func.sum(ServicePart.jumlah).label("jumlah_total"),
                func.count(ServicePart.id).label("jumlah_baris"),
            )
            .group_by(ServicePart.nama_part)
            .order_by(func.sum(ServicePart.jumlah).desc(), ServicePart.nama_part.asc())
            .all()
        )
        return [
            {"nama_part": nama, "jumlah": int(total or 0), "jumlah_servis": int(baris or 0)}
            for nama, total, baris in rows
        ]

    def vehicles_under_warranty(self, today: date | None = None) -> list[dict]:
        today = today or date.today()
        rows = (
            self._session.query(Vehicle, ServiceRecord.garansi_sampai, ServiceRecord.status_klaim)
            .join(ServiceRecord, ServiceRecord.vehicle_id == Vehicle.id)
            .filter(ServiceRecord.garansi_sampai.isnot(None))
            .filter(ServiceRecord.garansi_sampai >= today)
            .order_by(Vehicle.nopol, ServiceRecord.garansi_sampai.desc())
            .all()
        )
        seen: dict[int, dict] = {}
        for vehicle, garansi, status in rows:
            if vehicle.id not in seen:
                seen[vehicle.id] = {
                    "nopol": vehicle.nopol,
                    "nama_client": vehicle.nama_client,
                    "jenis_mobil": vehicle.jenis_mobil,
                    "garansi_sampai": garansi,
                    "status_klaim": status,
                }
        return list(seen.values())

    def activity_summary(self) -> dict:
        counts = {
            "jumlah_kendaraan": self.count_vehicles(),
            "jumlah_servis": self.count_service_records(),
            "jumlah_pekerjaan": int(self._session.scalar(func.count(ServiceJob.id)) or 0),
            "jumlah_part": int(self._session.scalar(func.count(ServicePart.id)) or 0),
        }
        totals = self.service_totals()
        return {**counts, "total_servis": totals["total_servis"]}

    def search_records_by_job(self, query: str) -> list[ServiceRecord]:
        like = f"%{query.strip()}%"
        return list(
            self._session.query(ServiceRecord)
            .join(ServiceJob, ServiceJob.service_record_id == ServiceRecord.id)
            .filter(ServiceJob.deskripsi.ilike(like))
            .order_by(ServiceRecord.waktu_service.desc())
            .distinct()
            .limit(20)
        )

    def recent_service_records(self, limit: int = 5) -> list[ServiceRecord]:
        """Most recent service records across ALL vehicles (newest first)."""
        return list(
            self._session.query(ServiceRecord)
            .options(selectinload(ServiceRecord.vehicle), selectinload(ServiceRecord.jobs))
            .order_by(ServiceRecord.waktu_service.desc(), ServiceRecord.id.desc())
            .limit(limit)
            .all()
        )

    def list_service_records(self, limit: int = 100, offset: int = 0) -> list[ServiceRecord]:
        """All service records across all vehicles (newest first, paginated)."""
        return list(
            self._session.query(ServiceRecord)
            .options(selectinload(ServiceRecord.vehicle), selectinload(ServiceRecord.jobs))
            .order_by(ServiceRecord.waktu_service.desc(), ServiceRecord.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def search_service_records(self, query: str) -> list[ServiceRecord]:
        """Search service records by plate or job description."""
        q = f"%{query.strip()}%"
        return list(
            self._session.query(ServiceRecord)
            .options(selectinload(ServiceRecord.vehicle), selectinload(ServiceRecord.jobs))
            .join(Vehicle, Vehicle.id == ServiceRecord.vehicle_id)
            .outerjoin(ServiceJob, ServiceJob.service_record_id == ServiceRecord.id)
            .filter((Vehicle.nopol.ilike(q)) | (ServiceJob.deskripsi.ilike(q)))
            .order_by(ServiceRecord.waktu_service.desc(), ServiceRecord.id.desc())
            .distinct()
            .limit(50)
            .all()
        )

    def profit_history(self, kind: str, start=None, end=None) -> list[dict]:
        """Transaction breakdown for 'barang' (parts) or 'jasa' (jobs)."""
        items = []
        records = self._session.query(ServiceRecord).options(
            selectinload(ServiceRecord.jobs), selectinload(ServiceRecord.parts)
        ).all()
        for r in records:
            if start is not None and r.waktu_service < start:
                continue
            if end is not None and r.waktu_service >= end:
                continue
            if kind == "barang":
                for p in r.parts:
                    modal = None
                    if p.stock_item_id is not None:
                        stock = self._session.get(StockItem, p.stock_item_id)
                        if stock is not None and stock.harga_modal is not None:
                            modal = to_decimal(stock.harga_modal * p.jumlah)
                    jual = to_decimal(p.subtotal)
                    untung = None
                    if jual is not None and modal is not None:
                        untung = to_decimal(jual - modal)
                    items.append({"tanggal": r.waktu_service, "nama": p.nama_part, "harga_jual": jual, "modal": modal, "keuntungan": untung})
            else:
                for j in r.jobs:
                    jual = to_decimal(j.subtotal)
                    items.append({"tanggal": r.waktu_service, "nama": j.deskripsi, "harga_jual": jual, "modal": None, "keuntungan": jual})
        items.sort(key=lambda x: x["tanggal"], reverse=True)
        return items

    def incomplete_vehicles_count(self) -> int:
        """Vehicles missing at least one of the key client/vehicle fields."""
        return int(
            self._session.query(func.count(Vehicle.id))
            .filter(
                (Vehicle.nama_client.is_(None))
                | (Vehicle.nomor_wa.is_(None))
                | (Vehicle.jenis_mobil.is_(None))
                | (Vehicle.tahun_mobil.is_(None))
                | (Vehicle.alamat_client.is_(None))
            )
            .scalar()
            or 0
        )

    def list_incomplete_vehicles(self) -> list[Vehicle]:
        """Vehicles that are missing at least one key client/vehicle field."""
        return list(
            self._session.query(Vehicle)
            .filter(
                (Vehicle.nama_client.is_(None))
                | (Vehicle.nomor_wa.is_(None))
                | (Vehicle.jenis_mobil.is_(None))
                | (Vehicle.tahun_mobil.is_(None))
                | (Vehicle.alamat_client.is_(None))
            )
            .order_by(Vehicle.nopol)
            .all()
        )



    def warranty_incomplete_count(self) -> int:
        """Service records whose warranty info has not been filled in yet."""
        return int(
            self._session.query(func.count(ServiceRecord.id))
            .filter(
                (ServiceRecord.bergaransi.is_(None))
                | ((ServiceRecord.bergaransi.is_(True)) & (ServiceRecord.garansi_sampai.is_(None)))
            )
            .scalar()
            or 0
        )

    def list_warranty_incomplete(self) -> list[ServiceRecord]:
        """Service records whose warranty info has not been filled in yet."""
        return list(
            self._session.query(ServiceRecord)
            .options(selectinload(ServiceRecord.vehicle))
            .filter(
                (ServiceRecord.bergaransi.is_(None))
                | ((ServiceRecord.bergaransi.is_(True)) & (ServiceRecord.garansi_sampai.is_(None)))
            )
            .order_by(ServiceRecord.waktu_service.desc(), ServiceRecord.id.desc())
            .all()
        )
