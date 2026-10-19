"""Minimal FastAPI application — foundation for a future localhost UI.

Exposes a public health check and a protected root. No customer-data or mutation
endpoints are exposed yet. API access is authenticated via a bearer token
(``UI_ACCESS_TOKEN``); documentation endpoints are disabled by default.
"""

from datetime import date, datetime, time, timedelta
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from api.schemas import (
    DashboardOut,
    HargaJasaCreate,
    HargaJasaOut,
    HargaJasaUpdate,
    IncompleteVehicleOut,
    ProfitHistoryItemOut,
    ProfitOut,
    RecentActivityOut,
    ServiceJobCreate,
    ServiceJobOut,
    ServiceJobPriceUpdate,
    ServicePartCreate,
    ServicePartOut,
    ServicePartPriceUpdate,
    ServiceRecordClaimUpdate,
    ServiceRecordCreate,
    ServiceRecordOut,
    ServiceRecordWarrantyUpdate,
    StockItemCreate,
    StockItemOut,
    StockItemUpdate,
    VehicleDetail,
    VehicleSummary,
    VehicleUpdate,
)
from database.models import HargaJasa, ServiceRecord, StockItem, Vehicle
from database.session import engine as db_engine, get_db, get_database_url, init_db
from whatsapp.db import init_whatsapp_db
from config.settings import get_internal_token
from services import backup as backup_service
from services.exceptions import ConflictError, NotFoundError, ValidationError
from services.harga_jasa_service import HargaJasaService
from services.reporting import ReportingService
from services.service_record_service import ServiceRecordService
from services.stock_service import StockService
from services.vehicle_service import VehicleService
from api.auth import require_ui_access
from api.integration_routes import int_router
from api.whatsapp_routes import wa_gateway_router, wa_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Non-destructive: creates the data dir and applies pending migrations.
    init_db()
    init_whatsapp_db()
    get_internal_token()
    yield


app = FastAPI(
    title="AI Bengkel API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ---------------------------------------------------------------------------
# Serialization helpers (Decimal -> str to preserve precision)
# ---------------------------------------------------------------------------
def _money(value) -> str | None:
    return None if value is None else str(value)


def _jasa_summary(record) -> str:
    return ", ".join(j.deskripsi for j in record.jobs)


_PERIODS = {"today", "week", "month", "year", "all"}


def _period_start(period: str) -> datetime | None:
    today = date.today()
    if period == "today":
        return datetime.combine(today, time.min)
    if period == "week":
        monday = today - timedelta(days=today.weekday())
        return datetime.combine(monday, time.min)
    if period == "month":
        return datetime.combine(today.replace(day=1), time.min)
    if period == "year":
        return datetime.combine(date(today.year, 1, 1), time.min)
    return None


_IMPORTANT_FIELDS = ("nama_client", "nomor_wa", "jenis_mobil", "tahun_mobil", "alamat_client")


def _missing_fields(vehicle: Vehicle) -> list[str]:
    return [f for f in _IMPORTANT_FIELDS if getattr(vehicle, f) is None]


def _vehicle_summary(v: Vehicle) -> VehicleSummary:
    return VehicleSummary(
        id=v.id, nopol=v.nopol, nama_client=v.nama_client, nomor_wa=v.nomor_wa,
        jenis_mobil=v.jenis_mobil, tahun_mobil=v.tahun_mobil, alamat_client=v.alamat_client,
    )


def _service_record_out(r: ServiceRecord) -> ServiceRecordOut:
    return ServiceRecordOut(
        id=r.id, vehicle_id=r.vehicle_id, waktu_service=r.waktu_service,
        biaya_jasa=_money(r.biaya_jasa), total_part=_money(r.total_part), total_servis=_money(r.total_servis),
        garansi_sampai=r.garansi_sampai, bergaransi=r.bergaransi, tanggal_klaim=r.tanggal_klaim, status_klaim=r.status_klaim, catatan=r.catatan,
        jobs=[ServiceJobOut(id=j.id, deskripsi=j.deskripsi, jumlah=j.jumlah, harga=_money(j.harga), subtotal=_money(j.subtotal)) for j in r.jobs],
        parts=[ServicePartOut(id=p.id, nama_part=p.nama_part, jumlah=p.jumlah, harga_satuan=_money(p.harga_satuan), subtotal=_money(p.subtotal), stock_item_id=p.stock_item_id) for p in r.parts],
    )


def _stock_item_out(item: StockItem) -> StockItemOut:
    keuntungan = None
    if item.harga_jual is not None and item.harga_modal is not None:
        keuntungan = item.harga_jual - item.harga_modal
    return StockItemOut(
        id=item.id,
        kode=item.kode,
        nama=item.nama,
        jumlah=item.jumlah,
        harga_modal=_money(item.harga_modal),
        harga_jual=_money(item.harga_jual),
        keuntungan=_money(keuntungan),
    )


def _harga_jasa_out(item: HargaJasa) -> HargaJasaOut:
    return HargaJasaOut(
        id=item.id,
        nama=item.nama,
        keuntungan=_money(item.keuntungan),
    )


@app.get("/")
def root(_: None = Depends(require_ui_access)):
    return {"name": "AI Bengkel API", "status": "running"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    reporting = ReportingService(db)
    recent = reporting.recent_service_records(limit=5)
    return DashboardOut(
        vehicle_count=reporting.count_vehicles(),
        service_record_count=reporting.count_service_records(),
        recent_service_records=[
            RecentActivityOut(
                id=r.id,
                waktu_service=r.waktu_service,
                nopol=r.vehicle.nopol,
                nama_client=r.vehicle.nama_client,
                total_servis=_money(r.total_servis),
                garansi_sampai=r.garansi_sampai,
                bergaransi=r.bergaransi,
                tanggal_klaim=r.tanggal_klaim,
                status_klaim=r.status_klaim,
                jasa=_jasa_summary(r),
            )
            for r in recent
        ],
        incomplete_vehicles_count=reporting.incomplete_vehicles_count(),
        warranty_incomplete_count=reporting.warranty_incomplete_count(),
    )


@app.get("/api/dashboard/profit", response_model=ProfitOut)
def dashboard_profit(period: str = "all", db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    if period not in _PERIODS:
        raise HTTPException(status_code=400, detail="period tidak valid")
    summary = ReportingService(db).profit_summary(start=_period_start(period))
    return ProfitOut(
        keuntungan_jasa=_money(summary["keuntungan_jasa"]),
        keuntungan_barang=_money(summary["keuntungan_barang"]),
        modal_barang=_money(summary["modal_barang"]),
        omset_barang=_money(summary["omset_barang"]),
    )


@app.get("/api/profit/history", response_model=list[ProfitHistoryItemOut])
def profit_history(kind: str = "barang", period: str = "all", db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    if period not in _PERIODS:
        raise HTTPException(status_code=400, detail="period tidak valid")
    if kind not in ("barang", "jasa"):
        raise HTTPException(status_code=400, detail="kind harus 'barang' atau 'jasa'")
    start = _period_start(period)
    items = ReportingService(db).profit_history(kind, start=start)
    return [
        ProfitHistoryItemOut(
            tanggal=i["tanggal"],
            nama=i["nama"],
            harga_jual=_money(i["harga_jual"]),
            modal=_money(i["modal"]),
            keuntungan=_money(i["keuntungan"]),
        )
        for i in items
    ]


@app.get("/api/vehicles", response_model=list[VehicleSummary])
def list_vehicles(
    limit: int = 50, offset: int = 0,
    db: Session = Depends(get_db), _: None = Depends(require_ui_access),
):
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit harus antara 1 dan 500")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset tidak boleh negatif")
    vehicles = VehicleService(db).list_vehicles(limit=limit, offset=offset)
    return [_vehicle_summary(v) for v in vehicles]


@app.get("/api/vehicles/search", response_model=list[VehicleSummary])
def search_vehicles(q: str, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    query = q.strip()
    if not query:
        return []
    results = VehicleService(db).search_vehicles_filtered(query)
    return [_vehicle_summary(v) for v in results]


@app.get("/api/vehicles/incomplete", response_model=list[IncompleteVehicleOut])
def list_incomplete_vehicles(db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    vehicles = ReportingService(db).list_incomplete_vehicles()
    return [
        IncompleteVehicleOut(
            id=v.id,
            nopol=v.nopol,
            nama_client=v.nama_client,
            missing_fields=_missing_fields(v),
        )
        for v in vehicles
    ]


@app.get("/api/vehicles/{vehicle_id}", response_model=VehicleDetail)
def get_vehicle_detail(vehicle_id: int, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    try:
        vehicle = VehicleService(db).get_vehicle(vehicle_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Kendaraan tidak ditemukan")
    return VehicleDetail(
        **_vehicle_summary(vehicle).model_dump(),
        missing_fields=_missing_fields(vehicle),
        service_record_count=len(vehicle.service_records),
    )


@app.put("/api/vehicles/{vehicle_id}", response_model=VehicleDetail)
def edit_vehicle(
    vehicle_id: int, payload: VehicleUpdate,
    db: Session = Depends(get_db), _: None = Depends(require_ui_access),
):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Tidak ada field yang diperbarui")
    try:
        vehicle = VehicleService(db).update_vehicle(vehicle_id, **changes)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Kendaraan tidak ditemukan")
    except ConflictError:
        raise HTTPException(status_code=409, detail="Plat nomor sudah terdaftar")
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return VehicleDetail(
        **_vehicle_summary(vehicle).model_dump(),
        missing_fields=_missing_fields(vehicle),
        service_record_count=len(vehicle.service_records),
    )


@app.delete("/api/vehicles/{vehicle_id}")
def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    try:
        VehicleService(db).delete_vehicle(vehicle_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Kendaraan tidak ditemukan")
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@app.get("/api/vehicles/{vehicle_id}/service-records", response_model=list[ServiceRecordOut])
def list_vehicle_service_records(
    vehicle_id: int, db: Session = Depends(get_db), _: None = Depends(require_ui_access)
):
    try:
        records = ServiceRecordService(db).list_service_records(vehicle_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Kendaraan tidak ditemukan")
    return [_service_record_out(r) for r in records]


@app.post("/api/vehicles/{vehicle_id}/service-records", response_model=ServiceRecordOut)
def create_service_record(
    vehicle_id: int, payload: ServiceRecordCreate,
    db: Session = Depends(get_db), _: None = Depends(require_ui_access),
):
    try:
        record = ServiceRecordService(db).add_service_record(
            vehicle_id,
            waktu_service=payload.waktu_service,
            garansi_sampai=payload.garansi_sampai,
            bergaransi=payload.bergaransi,
            catatan=payload.catatan,
            total_servis=payload.total_servis,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _service_record_out(record)


@app.get("/api/service-records", response_model=list[RecentActivityOut])
def list_service_records(limit: int = 100, offset: int = 0, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit harus antara 1 dan 500")
    records = ReportingService(db).list_service_records(limit=limit, offset=offset)
    return [
        RecentActivityOut(
            id=r.id,
            waktu_service=r.waktu_service,
            nopol=r.vehicle.nopol,
            nama_client=r.vehicle.nama_client,
            total_servis=_money(r.total_servis),
            garansi_sampai=r.garansi_sampai,
            bergaransi=r.bergaransi,
            tanggal_klaim=r.tanggal_klaim,
            status_klaim=r.status_klaim,
            jasa=_jasa_summary(r),
        )
        for r in records
    ]


@app.get("/api/service-records/recent", response_model=list[RecentActivityOut])
def recent_service_records(limit: int = 10, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit harus antara 1 dan 100")
    records = ReportingService(db).recent_service_records(limit=limit)
    return [
        RecentActivityOut(
            id=r.id,
            waktu_service=r.waktu_service,
            nopol=r.vehicle.nopol,
            nama_client=r.vehicle.nama_client,
            total_servis=_money(r.total_servis),
            garansi_sampai=r.garansi_sampai,
            bergaransi=r.bergaransi,
            tanggal_klaim=r.tanggal_klaim,
            status_klaim=r.status_klaim,
            jasa=_jasa_summary(r),
        )
        for r in records
    ]


@app.get("/api/service-records/search", response_model=list[RecentActivityOut])
def search_service_records(q: str = "", db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    if not q.strip():
        return []
    records = ReportingService(db).search_service_records(q)
    return [
        RecentActivityOut(
            id=r.id,
            waktu_service=r.waktu_service,
            nopol=r.vehicle.nopol,
            nama_client=r.vehicle.nama_client,
            total_servis=_money(r.total_servis),
            garansi_sampai=r.garansi_sampai,
            bergaransi=r.bergaransi,
            tanggal_klaim=r.tanggal_klaim,
            status_klaim=r.status_klaim,
            jasa=_jasa_summary(r),
        )
        for r in records
    ]


@app.get("/api/service-records/incomplete-warranty", response_model=list[RecentActivityOut])
def list_incomplete_warranty(db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    records = ReportingService(db).list_warranty_incomplete()
    return [
        RecentActivityOut(
            id=r.id,
            waktu_service=r.waktu_service,
            nopol=r.vehicle.nopol,
            nama_client=r.vehicle.nama_client,
            total_servis=_money(r.total_servis),
            garansi_sampai=r.garansi_sampai,
            bergaransi=r.bergaransi,
            tanggal_klaim=r.tanggal_klaim,
            status_klaim=r.status_klaim,
            jasa=_jasa_summary(r),
        )
        for r in records
    ]


@app.get("/api/service-records/{record_id}", response_model=ServiceRecordOut)
def get_service_record(record_id: int, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    try:
        record = ServiceRecordService(db).get_service_record(record_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Riwayat servis tidak ditemukan")
    return _service_record_out(record)


@app.delete("/api/service-records/{record_id}")
def delete_service_record(record_id: int, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    try:
        ServiceRecordService(db).delete_service_record(record_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@app.put("/api/service-records/{record_id}/claim", response_model=ServiceRecordOut)
def set_service_claim_status(
    record_id: int, payload: ServiceRecordClaimUpdate,
    db: Session = Depends(get_db), _: None = Depends(require_ui_access),
):
    try:
        record = ServiceRecordService(db).update_claim_status(record_id, payload.status_klaim, tanggal_klaim=payload.tanggal_klaim)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _service_record_out(record)


@app.put("/api/service-records/{record_id}/warranty", response_model=ServiceRecordOut)
def update_service_warranty(
    record_id: int, payload: ServiceRecordWarrantyUpdate,
    db: Session = Depends(get_db), _: None = Depends(require_ui_access),
):
    try:
        record = ServiceRecordService(db).update_warranty(record_id, payload.garansi_sampai, bergaransi=payload.bergaransi)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _service_record_out(record)


@app.put("/api/service-jobs/{job_id}", response_model=ServiceRecordOut)
def update_service_job_price(
    job_id: int, payload: ServiceJobPriceUpdate,
    db: Session = Depends(get_db), _: None = Depends(require_ui_access),
):
    try:
        record = ServiceRecordService(db).update_job_price(job_id, payload.harga)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _service_record_out(record)


@app.put("/api/service-parts/{part_id}", response_model=ServiceRecordOut)
def update_service_part_price(
    part_id: int, payload: ServicePartPriceUpdate,
    db: Session = Depends(get_db), _: None = Depends(require_ui_access),
):
    try:
        record = ServiceRecordService(db).update_part_price(part_id, payload.harga_satuan)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _service_record_out(record)


@app.post("/api/service-records/{record_id}/jobs", response_model=ServiceRecordOut)
def add_service_job(
    record_id: int, payload: ServiceJobCreate,
    db: Session = Depends(get_db), _: None = Depends(require_ui_access),
):
    try:
        record = ServiceRecordService(db).add_job_to_record(
            record_id, payload.deskripsi, payload.jumlah, payload.harga,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _service_record_out(record)


@app.post("/api/service-records/{record_id}/parts", response_model=ServiceRecordOut)
def add_service_part(
    record_id: int, payload: ServicePartCreate,
    db: Session = Depends(get_db), _: None = Depends(require_ui_access),
):
    try:
        record = ServiceRecordService(db).add_part_to_record(
            record_id, payload.nama_part, payload.jumlah, payload.harga_satuan, payload.stock_item_id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _service_record_out(record)


@app.get("/api/stock", response_model=list[StockItemOut])
def list_stock(db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    return [_stock_item_out(i) for i in StockService(db).list_items()]


@app.post("/api/stock", response_model=StockItemOut)
def create_stock(payload: StockItemCreate, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    try:
        item = StockService(db).create_item(
            payload.nama, payload.kode, payload.harga_modal, payload.harga_jual, payload.jumlah,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _stock_item_out(item)


@app.put("/api/stock/{item_id}", response_model=StockItemOut)
def update_stock(item_id: int, payload: StockItemUpdate, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    changes = payload.model_dump(exclude_unset=True)
    try:
        item = StockService(db).update_item(item_id, **changes)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _stock_item_out(item)


@app.delete("/api/stock/{item_id}")
def delete_stock(item_id: int, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    try:
        StockService(db).delete_item(item_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@app.get("/api/harga-jasa", response_model=list[HargaJasaOut])
def list_harga_jasa(db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    return [_harga_jasa_out(i) for i in HargaJasaService(db).list_items()]


@app.post("/api/harga-jasa", response_model=HargaJasaOut)
def create_harga_jasa(payload: HargaJasaCreate, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    try:
        item = HargaJasaService(db).create_item(payload.nama, payload.keuntungan)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _harga_jasa_out(item)


@app.put("/api/harga-jasa/{item_id}", response_model=HargaJasaOut)
def update_harga_jasa(item_id: int, payload: HargaJasaUpdate, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    changes = payload.model_dump(exclude_unset=True)
    try:
        item = HargaJasaService(db).update_item(item_id, **changes)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _harga_jasa_out(item)


@app.delete("/api/harga-jasa/{item_id}")
def delete_harga_jasa(item_id: int, db: Session = Depends(get_db), _: None = Depends(require_ui_access)):
    try:
        HargaJasaService(db).delete_item(item_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@app.post("/api/admin/backup")
def create_backup_endpoint(_: None = Depends(require_ui_access)):
    try:
        return backup_service.create_backup(get_database_url())
    except backup_service.BackupError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/admin/restore")
async def restore_endpoint(request: Request, _: None = Depends(require_ui_access)):
    body = await request.body()
    if len(body) == 0:
        raise HTTPException(status_code=400, detail="File kosong")
    if len(body) > backup_service.DEFAULT_MAX_BACKUP_BYTES:
        raise HTTPException(status_code=413, detail="File terlalu besar")
    # Close pooled connections before replacing the database file.
    db_engine.dispose()
    try:
        return backup_service.restore_from_file(get_database_url(), body)
    except backup_service.BackupError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ---------------------------------------------------------------------------
# Local browser UI (H8F) — a public static shell (no data or secrets). All data
# stays behind the authenticated /api/* endpoints above.
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/ui", include_in_schema=False)
def ui_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(wa_router)
app.include_router(wa_gateway_router)
app.include_router(int_router)

