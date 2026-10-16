"""Service record service: business rules for service history, jobs, parts, warranty."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import (
    CLAIM_BELUM,
    CLAIM_SUDAH,
    ServiceJob,
    ServicePart,
    ServiceRecord,
    Vehicle,
    normalize_plate,
    utcnow,
)
from repositories.service_record_repository import ServiceRecordRepository
from repositories.vehicle_repository import VehicleRepository
from services.exceptions import ConflictError, NotFoundError
from services.pricing import grand_total, item_subtotal, total_of
from services.stock_service import StockService
from services.validation import (
    clean_optional,
    clean_required,
    coerce_date,
    coerce_datetime,
    normalize_required_plate,
    normalize_warranty,
    validate_price,
    validate_quantity,
    validate_status_klaim,
    validate_tahun,
)


class ServiceRecordService:
    """Add and query service records with jobs, parts, totals and warranty.

    A new service visit always creates a *new* record (never overwrites an
    older one). Jobs and parts are stored together with the record in a single
    atomic transaction; subtotals and totals are computed here with Decimal.
    """

    def __init__(self, session: Session):
        self._session = session
        self._vehicle_repository = VehicleRepository(session)
        self._record_repository = ServiceRecordRepository(session)

    def add_service_record(
        self,
        vehicle_id: int,
        *,
        jobs=None,
        parts=None,
        waktu_service=None,
        garansi_sampai=None,
        bergaransi=None,
        catatan=None,
        status_klaim=None,
        total_servis=None,
        commit=True,
    ) -> ServiceRecord:
        vehicle = self._vehicle_repository.get(vehicle_id)
        if vehicle is None:
            raise NotFoundError(f"Kendaraan dengan id {vehicle_id} tidak ditemukan.")

        bergaransi, garansi_sampai = normalize_warranty(bergaransi, garansi_sampai)

        job_objects = self._build_jobs(jobs or [])
        part_objects = self._build_parts(parts or [])

        biaya_jasa = total_of([j.subtotal for j in job_objects])
        total_part = total_of([p.subtotal for p in part_objects])
        if total_servis is not None:
            # User-provided total overrides the computed grand total.
            total_servis = validate_price(total_servis)
            # For a total-only entry, an absent jobs/parts list means the
            # breakdown is unknown — never presented as zero.
            if not job_objects:
                biaya_jasa = None
            if not part_objects:
                total_part = None
        else:
            total_servis = grand_total(biaya_jasa, total_part)

        record = ServiceRecord(
            vehicle_id=vehicle_id,
            waktu_service=coerce_datetime(waktu_service) if waktu_service is not None else utcnow(),
            garansi_sampai=garansi_sampai,
            bergaransi=bergaransi,
            catatan=clean_optional(catatan),
            status_klaim=validate_status_klaim(status_klaim) if status_klaim is not None else CLAIM_BELUM,
            biaya_jasa=biaya_jasa,
            total_part=total_part,
            total_servis=total_servis,
            jobs=job_objects,
            parts=part_objects,
        )
        self._record_repository.add(record)
        if commit:
            self._commit()
        else:
            self._session.flush()
        return record

    def record_service_visit(
        self,
        *,
        nopol,
        nama_client=None,
        nomor_wa=None,
        jenis_mobil=None,
        tahun_mobil=None,
        alamat_client=None,
        jobs=None,
        parts=None,
        waktu_service=None,
        garansi_sampai=None,
        bergaransi=None,
        catatan=None,
        total_servis=None,
        commit=True,
    ) -> ServiceRecord:
        """Record a service visit, creating the vehicle if it does not exist yet.

        This is the single atomic operation behind the AI flow: the vehicle and
        its first service record are written in ONE transaction (commit or
        rollback together), so a new vehicle can never be left without a
        service record. For an existing plate, a new service record is simply
        appended and no vehicle fields are modified.
        """
        nopol_norm = normalize_required_plate(nopol)
        vehicle = self._vehicle_repository.find_by_plate(nopol_norm)

        if vehicle is None:
            vehicle = Vehicle(
                nama_client=clean_optional(nama_client),
                nopol=nopol_norm,
                nomor_wa=clean_optional(nomor_wa),
                jenis_mobil=clean_optional(jenis_mobil),
                tahun_mobil=validate_tahun(tahun_mobil),
                alamat_client=clean_optional(alamat_client),
            )
            self._vehicle_repository.add(vehicle)

        bergaransi, garansi_sampai = normalize_warranty(bergaransi, garansi_sampai)

        job_objects = self._build_jobs(jobs or [])
        part_objects = self._build_parts(parts or [])

        biaya_jasa = total_of([j.subtotal for j in job_objects])
        total_part = total_of([p.subtotal for p in part_objects])
        if total_servis is not None:
            total_servis = validate_price(total_servis)
            if not job_objects:
                biaya_jasa = None
            if not part_objects:
                total_part = None
        else:
            total_servis = grand_total(biaya_jasa, total_part)

        record = ServiceRecord(
            vehicle=vehicle,
            waktu_service=coerce_datetime(waktu_service) if waktu_service is not None else utcnow(),
            garansi_sampai=garansi_sampai,
            bergaransi=bergaransi,
            catatan=clean_optional(catatan),
            status_klaim=CLAIM_BELUM,
            biaya_jasa=biaya_jasa,
            total_part=total_part,
            total_servis=total_servis,
            jobs=job_objects,
            parts=part_objects,
        )
        self._record_repository.add(record)
        if commit:
            self._commit()
        else:
            self._session.flush()
        return record

    def get_service_record(self, record_id: int) -> ServiceRecord:
        record = self._record_repository.get(record_id)
        if record is None:
            raise NotFoundError(f"Riwayat servis dengan id {record_id} tidak ditemukan.")
        return record

    def list_service_records(self, vehicle_id: int) -> list[ServiceRecord]:
        if self._vehicle_repository.get(vehicle_id) is None:
            raise NotFoundError(f"Kendaraan dengan id {vehicle_id} tidak ditemukan.")
        return self._record_repository.list_by_vehicle(vehicle_id)

    def get_vehicle_service_history(self, nopol: str) -> list[ServiceRecord]:
        vehicle = self._vehicle_repository.find_by_plate(nopol)
        if vehicle is None:
            raise NotFoundError(f"Kendaraan dengan plat {normalize_plate(nopol)} tidak ditemukan.")
        return self._record_repository.list_by_vehicle(vehicle.id)

    def update_warranty(self, record_id: int, garansi_sampai=None, bergaransi=None, commit=True) -> ServiceRecord:
        record = self._record_repository.get(record_id)
        if record is None:
            raise NotFoundError(f"Riwayat servis dengan id {record_id} tidak ditemukan.")
        b, d = normalize_warranty(bergaransi, garansi_sampai)
        record.bergaransi = b
        record.garansi_sampai = d
        if commit:
            self._commit()
        else:
            self._session.flush()
        return record

    def mark_claim(self, record_id: int, tanggal_klaim=None, commit=True) -> ServiceRecord:
        record = self._record_repository.get(record_id)
        if record is None:
            raise NotFoundError(f"Riwayat servis dengan id {record_id} tidak ditemukan.")
        record.status_klaim = CLAIM_SUDAH
        if tanggal_klaim is not None:
            record.tanggal_klaim = coerce_date(tanggal_klaim)
        if commit:
            self._commit()
        else:
            self._session.flush()
        return record

    def update_job_price(self, job_id: int, harga, commit=True) -> ServiceRecord:
        """Set the unit price of a job and recompute the record's totals."""
        job = self._session.get(ServiceJob, job_id)
        if job is None:
            raise NotFoundError(f"Pekerjaan dengan id {job_id} tidak ditemukan.")
        record = self._record_repository.get(job.service_record_id)
        if record is None:
            raise NotFoundError("Riwayat servis tidak ditemukan.")
        job.harga = validate_price(harga)
        job.subtotal = item_subtotal(job.jumlah, job.harga)
        self._recompute_totals(record)
        if commit:
            self._commit()
        else:
            self._session.flush()
        return record

    def update_part_price(self, part_id: int, harga_satuan, commit=True) -> ServiceRecord:
        """Set the unit price of a part and recompute the record's totals."""
        part = self._session.get(ServicePart, part_id)
        if part is None:
            raise NotFoundError(f"Suku cadang dengan id {part_id} tidak ditemukan.")
        record = self._record_repository.get(part.service_record_id)
        if record is None:
            raise NotFoundError("Riwayat servis tidak ditemukan.")
        part.harga_satuan = validate_price(harga_satuan)
        part.subtotal = item_subtotal(part.jumlah, part.harga_satuan)
        self._recompute_totals(record)
        if commit:
            self._commit()
        else:
            self._session.flush()
        return record

    def _recompute_totals(self, record: ServiceRecord) -> None:
        """Recalculate biaya_jasa/total_part/total_servis from jobs and parts."""
        biaya_jasa = total_of([j.subtotal for j in record.jobs])
        total_part = total_of([p.subtotal for p in record.parts])
        record.biaya_jasa = biaya_jasa
        record.total_part = total_part
        record.total_servis = grand_total(biaya_jasa, total_part)

    def add_job_to_record(self, record_id: int, deskripsi, jumlah=1, harga=None, commit=True) -> ServiceRecord:
        """Add a new job line item to an existing service record."""
        record = self._record_repository.get(record_id)
        if record is None:
            raise NotFoundError(f"Riwayat servis dengan id {record_id} tidak ditemukan.")
        job = ServiceJob(
            deskripsi=clean_required(deskripsi, "Deskripsi pekerjaan"),
            jumlah=validate_quantity(jumlah),
        )
        job.harga = validate_price(harga)
        job.subtotal = item_subtotal(job.jumlah, job.harga)
        record.jobs.append(job)
        self._recompute_totals(record)
        if commit:
            self._commit()
        else:
            self._session.flush()
        return record

    def add_part_to_record(self, record_id: int, nama_part, jumlah=1, harga_satuan=None, stock_item_id=None, commit=True) -> ServiceRecord:
        """Add a new spare-part line item, optionally linking + deducting stock."""
        record = self._record_repository.get(record_id)
        if record is None:
            raise NotFoundError(f"Riwayat servis dengan id {record_id} tidak ditemukan.")
        part = ServicePart(
            nama_part=clean_required(nama_part, "Nama part"),
            jumlah=validate_quantity(jumlah),
        )
        part.harga_satuan = validate_price(harga_satuan)
        part.subtotal = item_subtotal(part.jumlah, part.harga_satuan)
        if stock_item_id is not None:
            StockService(self._session).adjust_stock(stock_item_id, -part.jumlah, commit=False)
            part.stock_item_id = stock_item_id
        record.parts.append(part)
        self._recompute_totals(record)
        if commit:
            self._commit()
        else:
            self._session.flush()
        return record

    def delete_service_record(self, record_id: int, commit=True) -> None:
        """Delete a service record together with its jobs and parts (restoring stock)."""
        record = self._record_repository.get(record_id)
        if record is None:
            raise NotFoundError(f"Riwayat servis dengan id {record_id} tidak ditemukan.")
        for j in list(record.jobs):
            self._session.delete(j)
        for p in list(record.parts):
            if p.stock_item_id is not None:
                StockService(self._session).adjust_stock(p.stock_item_id, p.jumlah, commit=False)
            self._session.delete(p)
        self._session.delete(record)
        if commit:
            self._commit()
        else:
            self._session.flush()

    def update_claim_status(self, record_id: int, status, tanggal_klaim=None, commit=True) -> ServiceRecord:
        """Set the warranty claim status (Belum claim / Sudah claim)."""
        record = self._record_repository.get(record_id)
        if record is None:
            raise NotFoundError(f"Riwayat servis dengan id {record_id} tidak ditemukan.")
        status = validate_status_klaim(status)
        record.status_klaim = status
        if status == CLAIM_SUDAH:
            if tanggal_klaim is not None:
                record.tanggal_klaim = coerce_date(tanggal_klaim)
        else:
            record.tanggal_klaim = None
        if commit:
            self._commit()
        else:
            self._session.flush()
        return record

    def _build_jobs(self, jobs) -> list[ServiceJob]:
        built = []
        for item in jobs:
            deskripsi = clean_required(item.get("deskripsi"), "Deskripsi pekerjaan")
            jumlah = validate_quantity(item.get("jumlah", 1))
            harga = validate_price(item.get("harga"))
            subtotal = item_subtotal(jumlah, harga)
            built.append(ServiceJob(deskripsi=deskripsi, jumlah=jumlah, harga=harga, subtotal=subtotal))
        return built

    def _build_parts(self, parts) -> list[ServicePart]:
        built = []
        for item in parts:
            nama_part = clean_required(item.get("nama_part"), "Nama part")
            jumlah = validate_quantity(item.get("jumlah", 1))
            harga_satuan = validate_price(item.get("harga_satuan"))
            subtotal = item_subtotal(jumlah, harga_satuan)
            built.append(ServicePart(nama_part=nama_part, jumlah=jumlah, harga_satuan=harga_satuan, subtotal=subtotal))
        return built

    def _commit(self) -> None:
        try:
            self._session.commit()
        except IntegrityError:
            self._session.rollback()
            raise ConflictError("Penyimpanan gagal karena konflik data.")
        except Exception:
            self._session.rollback()
            raise
