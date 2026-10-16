"""Repository for Vehicle persistence operations.

Repositories only perform data access on a supplied session. They contain no
business rules and never commit/rollback the transaction (that is the service
layer's responsibility).
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import Vehicle, normalize_plate


class VehicleRepository:
    """Thin data-access for vehicles."""

    def __init__(self, session: Session):
        self._session = session

    def get(self, vehicle_id: int) -> Optional[Vehicle]:
        return self._session.get(Vehicle, vehicle_id)

    def find_by_plate(self, nopol: str) -> Optional[Vehicle]:
        normalized = normalize_plate(nopol)
        return self._session.scalar(select(Vehicle).where(Vehicle.nopol == normalized))

    def list_all(self, limit: int | None = None, offset: int = 0) -> list[Vehicle]:
        stmt = select(Vehicle).order_by(Vehicle.nopol).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self._session.scalars(stmt))

    def search(self, query: str) -> list[Vehicle]:
        like = f"%{query.strip()}%"
        return list(
            self._session.scalars(
                select(Vehicle)
                .where((Vehicle.nama_client.ilike(like)) | (Vehicle.nopol.ilike(like)))
                .order_by(Vehicle.nopol)
                .limit(20)
            )
        )

    def search_filtered(
        self,
        query: str | None = None,
        jenis_mobil: str | None = None,
        tahun_mobil: int | None = None,
    ) -> list[Vehicle]:
        """Search by name/plate (free text), vehicle type, and/or year."""
        stmt = select(Vehicle)
        q = (query or "").strip()
        if q:
            like = f"%{q}%"
            norm_like = f"%{normalize_plate(q)}%"
            stmt = stmt.where(
                (Vehicle.nama_client.ilike(like))
                | (Vehicle.nopol.ilike(like))
                | (Vehicle.nopol.ilike(norm_like))
                | (Vehicle.jenis_mobil.ilike(like))
            )
        if jenis_mobil:
            stmt = stmt.where(Vehicle.jenis_mobil.ilike(f"%{jenis_mobil.strip()}%"))
        if tahun_mobil is not None:
            stmt = stmt.where(Vehicle.tahun_mobil == int(tahun_mobil))
        return list(self._session.scalars(stmt.order_by(Vehicle.nopol).limit(20)))

    def add(self, vehicle: Vehicle) -> Vehicle:
        self._session.add(vehicle)
        return vehicle

    def delete(self, vehicle: Vehicle) -> None:
        self._session.delete(vehicle)
