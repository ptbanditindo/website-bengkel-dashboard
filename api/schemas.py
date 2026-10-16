"""Pydantic response schemas for the read-only API (H8C).

Money values are serialized as strings (``str(Decimal)``) to preserve exact
Decimal precision. Dates/times use their native ISO serialization.
"""

from datetime import date, datetime

from pydantic import BaseModel


class VehicleSummary(BaseModel):
    id: int
    nopol: str
    nama_client: str | None
    nomor_wa: str | None
    jenis_mobil: str | None
    tahun_mobil: int | None
    alamat_client: str | None


class VehicleDetail(VehicleSummary):
    missing_fields: list[str]
    service_record_count: int


class IncompleteVehicleOut(BaseModel):
    id: int
    nopol: str
    nama_client: str | None
    missing_fields: list[str]


class ServiceJobOut(BaseModel):
    id: int
    deskripsi: str
    jumlah: int
    harga: str | None
    subtotal: str | None


class ServicePartOut(BaseModel):
    id: int
    nama_part: str
    jumlah: int
    harga_satuan: str | None
    subtotal: str | None
    stock_item_id: int | None


class ServiceRecordOut(BaseModel):
    id: int
    vehicle_id: int
    waktu_service: datetime
    biaya_jasa: str | None
    total_part: str | None
    total_servis: str | None
    garansi_sampai: date | None
    bergaransi: bool | None
    tanggal_klaim: date | None
    status_klaim: str
    catatan: str | None
    jobs: list[ServiceJobOut]
    parts: list[ServicePartOut]


class RecentActivityOut(BaseModel):
    id: int
    waktu_service: datetime
    nopol: str
    nama_client: str | None
    total_servis: str | None
    garansi_sampai: date | None
    bergaransi: bool | None
    tanggal_klaim: date | None
    status_klaim: str
    jasa: str


class DashboardOut(BaseModel):
    vehicle_count: int
    service_record_count: int
    recent_service_records: list[RecentActivityOut]
    incomplete_vehicles_count: int
    warranty_incomplete_count: int


class VehicleUpdate(BaseModel):
    """Editable vehicle fields (partial update: only provided fields change)."""

    nama_client: str | None = None
    nomor_wa: str | None = None
    nopol: str | None = None
    jenis_mobil: str | None = None
    tahun_mobil: int | None = None
    alamat_client: str | None = None


class ServiceJobPriceUpdate(BaseModel):
    """Update the unit price of a service job (empty string clears it)."""

    harga: str


class ServicePartPriceUpdate(BaseModel):
    """Update the unit price of a spare part (empty string clears it)."""

    harga_satuan: str


class ServiceJobCreate(BaseModel):
    """Create a new service job line item for an existing record."""

    deskripsi: str
    jumlah: int = 1
    harga: str | None = None


class ServicePartCreate(BaseModel):
    """Create a new spare-part line item for an existing record."""

    nama_part: str
    jumlah: int = 1
    harga_satuan: str | None = None
    stock_item_id: int | None = None


class ServiceRecordCreate(BaseModel):
    """Create a new service record for an existing vehicle."""

    waktu_service: str | None = None
    garansi_sampai: str | None = None
    bergaransi: bool | None = None
    catatan: str | None = None
    total_servis: str | None = None


class ServiceRecordClaimUpdate(BaseModel):
    """Toggle the warranty claim status of a service record."""

    status_klaim: str
    tanggal_klaim: str | None = None


class ServiceRecordWarrantyUpdate(BaseModel):
    """Update the warranty expiry date of a service record (empty clears it)."""

    garansi_sampai: str | None = None
    bergaransi: bool | None = None


class ProfitOut(BaseModel):
    """Gross income (keuntungan kotor) from services and parts."""

    keuntungan_jasa: str | None
    keuntungan_barang: str | None
    modal_barang: str | None
    omset_barang: str | None


class StockItemOut(BaseModel):
    id: int
    kode: str | None
    nama: str
    jumlah: int
    harga_modal: str | None
    harga_jual: str | None
    keuntungan: str | None


class StockItemCreate(BaseModel):
    nama: str
    kode: str | None = None
    jumlah: int = 0
    harga_modal: str | None = None
    harga_jual: str | None = None


class StockItemUpdate(BaseModel):
    nama: str | None = None
    kode: str | None = None
    jumlah: int | None = None
    harga_modal: str | None = None
    harga_jual: str | None = None


class HargaJasaOut(BaseModel):
    id: int
    nama: str
    keuntungan: str | None


class HargaJasaCreate(BaseModel):
    nama: str
    keuntungan: str | None = None


class HargaJasaUpdate(BaseModel):
    nama: str | None = None
    keuntungan: str | None = None


class ProfitHistoryItemOut(BaseModel):
    tanggal: datetime
    nama: str
    harga_jual: str | None
    modal: str | None
    keuntungan: str | None

