"""Repository for ServiceRecord persistence operations."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from database.models import ServiceRecord


class ServiceRecordRepository:
    """Thin data-access for service records.

    Records are always loaded together with their jobs and parts so that the
    result can be safely serialized even after the session is closed.
    """

    def __init__(self, session: Session):
        self._session = session

    def get(self, record_id: int) -> Optional[ServiceRecord]:
        return self._session.scalar(
            select(ServiceRecord)
            .where(ServiceRecord.id == record_id)
            .options(selectinload(ServiceRecord.jobs), selectinload(ServiceRecord.parts))
        )

    def list_by_vehicle(self, vehicle_id: int) -> list[ServiceRecord]:
        return list(
            self._session.scalars(
                select(ServiceRecord)
                .where(ServiceRecord.vehicle_id == vehicle_id)
                .options(selectinload(ServiceRecord.jobs), selectinload(ServiceRecord.parts))
                .order_by(ServiceRecord.waktu_service.desc())
            )
        )

    def add(self, record: ServiceRecord) -> ServiceRecord:
        self._session.add(record)
        return record
