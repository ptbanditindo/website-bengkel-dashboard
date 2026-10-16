"""Workshop domain models: Vehicle, ServiceRecord, ServiceJob, ServicePart.

Money values use ``Numeric(14, 2)`` (mapped to ``decimal.Decimal``) so that
subtotals and totals are computed precisely by the application, never by an AI.

Plate numbers must be normalized before being persisted; see
:func:`normalize_plate`. The ``nopol`` column has a unique constraint so that
the same plate can never produce a duplicate vehicle record.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CLAIM_BELUM = "Belum claim"
CLAIM_SUDAH = "Sudah claim"
CLAIM_STATUSES = (CLAIM_BELUM, CLAIM_SUDAH)


def utcnow() -> datetime:
    """Return a timezone-naive UTC datetime (safe for SQLite storage)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_plate(value: str) -> str:
    """Normalize a plate number for consistent identity comparison.

    - Uppercases all letters.
    - Removes all whitespace (``"B 1234 ABC"`` -> ``"B1234ABC"``).
    """
    if value is None:
        return ""
    return "".join(str(value).upper().split())


class Vehicle(Base):
    """A single vehicle, identified by its normalized plate number."""

    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nama_client: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    nomor_wa: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    nopol: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    jenis_mobil: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tahun_mobil: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    alamat_client: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    service_records: Mapped[list["ServiceRecord"]] = relationship(
        back_populates="vehicle",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class ServiceRecord(Base):
    """A single service visit. A vehicle may have many service records."""

    __tablename__ = "service_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    waktu_service: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    catatan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    biaya_jasa: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    total_part: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    total_servis: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)

    garansi_sampai: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    bergaransi: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    tanggal_klaim: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status_klaim: Mapped[str] = mapped_column(String(32), nullable=False, default=CLAIM_BELUM)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    vehicle: Mapped["Vehicle"] = relationship(back_populates="service_records")
    jobs: Mapped[list["ServiceJob"]] = relationship(
        back_populates="service_record",
        cascade="save-update, merge",
        passive_deletes=True,
    )
    parts: Mapped[list["ServicePart"]] = relationship(
        back_populates="service_record",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class ServiceJob(Base):
    """A single job/service performed during a service visit."""

    __tablename__ = "service_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_record_id: Mapped[int] = mapped_column(
        ForeignKey("service_records.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    deskripsi: Mapped[str] = mapped_column(String(255), nullable=False)
    jumlah: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Unit price and subtotal are computed by the application; NULL until known.
    harga: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    subtotal: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)

    service_record: Mapped["ServiceRecord"] = relationship(back_populates="jobs")


class ServicePart(Base):
    """A single spare part replaced during a service visit."""

    __tablename__ = "service_parts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_record_id: Mapped[int] = mapped_column(
        ForeignKey("service_records.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    nama_part: Mapped[str] = mapped_column(String(255), nullable=False)
    jumlah: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Unit price and subtotal are computed by the application; NULL until known.
    harga_satuan: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    subtotal: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    stock_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    service_record: Mapped["ServiceRecord"] = relationship(back_populates="parts")


class StockItem(Base):
    """A spare part / item kept in stock, with cost, price and quantity."""

    __tablename__ = "stock_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kode: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    nama: Mapped[str] = mapped_column(String(255), nullable=False)
    harga_modal: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    harga_jual: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    jumlah: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class HargaJasa(Base):
    """A service price-list entry (labour profit / price)."""

    __tablename__ = "harga_jasa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nama: Mapped[str] = mapped_column(String(255), nullable=False)
    keuntungan: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

