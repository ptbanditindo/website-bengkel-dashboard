"""Vehicle service: business rules for vehicle CRUD."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import Vehicle
from repositories.vehicle_repository import VehicleRepository
from services.exceptions import ConflictError, NotFoundError
from services.validation import (
    clean_optional,
    normalize_required_plate,
    validate_tahun,
)


class VehicleService:
    """Create, find, update and delete vehicles with plate normalization.

    Business rules:
    - The plate is normalized (uppercase, whitespace removed) and unique.
    - A vehicle that still has service records cannot be deleted.
    """

    def __init__(self, session: Session):
        self._session = session
        self._repository = VehicleRepository(session)

    def create_vehicle(
        self,
        *,
        nama_client,
        nopol,
        nomor_wa=None,
        jenis_mobil=None,
        tahun_mobil=None,
        alamat_client=None,
        commit=True,
    ) -> Vehicle:
        nama = clean_optional(nama_client)
        normalized = normalize_required_plate(nopol)
        tahun = validate_tahun(tahun_mobil)

        if self._repository.find_by_plate(normalized) is not None:
            raise ConflictError(f"Kendaraan dengan plat {normalized} sudah terdaftar.")

        vehicle = Vehicle(
            nama_client=nama,
            nopol=normalized,
            nomor_wa=clean_optional(nomor_wa),
            jenis_mobil=clean_optional(jenis_mobil),
            tahun_mobil=tahun,
            alamat_client=clean_optional(alamat_client),
        )
        self._repository.add(vehicle)
        if commit:
            self._commit(conflict=f"Kendaraan dengan plat {normalized} sudah terdaftar.")
        else:
            self._session.flush()
        return vehicle

    def get_vehicle(self, vehicle_id: int) -> Vehicle:
        vehicle = self._repository.get(vehicle_id)
        if vehicle is None:
            raise NotFoundError(f"Kendaraan dengan id {vehicle_id} tidak ditemukan.")
        return vehicle

    def find_vehicle_by_plate(self, nopol: str) -> Vehicle | None:
        return self._repository.find_by_plate(nopol)

    def list_vehicles(self, limit: int | None = None, offset: int = 0) -> list[Vehicle]:
        return self._repository.list_all(limit=limit, offset=offset)

    def search_vehicles(self, query: str) -> list[Vehicle]:
        q = (query or "").strip()
        if not q:
            return []
        return self._repository.search(q)

    def search_vehicles_filtered(
        self, query: str = "", jenis_mobil: str | None = None, tahun_mobil=None
    ) -> list[Vehicle]:
        return self._repository.search_filtered(query, jenis_mobil, tahun_mobil)

    def update_vehicle(self, vehicle_id: int, commit=True, **changes) -> Vehicle:
        vehicle = self._repository.get(vehicle_id)
        if vehicle is None:
            raise NotFoundError(f"Kendaraan dengan id {vehicle_id} tidak ditemukan.")

        if "nama_client" in changes:
            vehicle.nama_client = clean_optional(changes["nama_client"])
        if "nomor_wa" in changes:
            vehicle.nomor_wa = clean_optional(changes["nomor_wa"])
        if "jenis_mobil" in changes:
            vehicle.jenis_mobil = clean_optional(changes["jenis_mobil"])
        if "tahun_mobil" in changes:
            vehicle.tahun_mobil = validate_tahun(changes["tahun_mobil"])
        if "alamat_client" in changes:
            vehicle.alamat_client = clean_optional(changes["alamat_client"])
        if "nopol" in changes:
            normalized = normalize_required_plate(changes["nopol"])
            existing = self._repository.find_by_plate(normalized)
            if existing is not None and existing.id != vehicle.id:
                raise ConflictError(f"Kendaraan dengan plat {normalized} sudah terdaftar.")
            vehicle.nopol = normalized

        if commit:
            self._commit(conflict="Kendaraan dengan plat tersebut sudah terdaftar.")
        else:
            self._session.flush()
        return vehicle

    def delete_vehicle(self, vehicle_id: int) -> None:
        vehicle = self._repository.get(vehicle_id)
        if vehicle is None:
            raise NotFoundError(f"Kendaraan dengan id {vehicle_id} tidak ditemukan.")

        if len(vehicle.service_records) > 0:
            raise ConflictError("Kendaraan yang memiliki riwayat servis tidak boleh dihapus.")

        self._repository.delete(vehicle)
        self._commit(conflict="Kendaraan yang memiliki riwayat servis tidak boleh dihapus.")

    def _commit(self, conflict: str) -> None:
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            raise ConflictError(conflict)
        except Exception:
            self._session.rollback()
            raise
