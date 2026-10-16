"""Pure formatting helpers for Telegram messages."""

from datetime import date
from decimal import Decimal

from database.models import ServiceRecord, Vehicle


def format_rupiah(value) -> str:
    if value is None:
        return "belum diketahui"
    return f"Rp{Decimal(value):,.0f}".replace(",", ".")


def format_date(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "belum diketahui"


def format_vehicle(vehicle: Vehicle) -> str:
    lines = [
        f"🚗 {vehicle.nopol}",
        f"👤 Client: {vehicle.nama_client}",
    ]
    if vehicle.jenis_mobil:
        lines.append(f"🔧 Jenis: {vehicle.jenis_mobil}")
    if vehicle.tahun_mobil:
        lines.append(f"📅 Tahun: {vehicle.tahun_mobil}")
    if vehicle.nomor_wa:
        lines.append(f"📱 WA: {vehicle.nomor_wa}")
    if vehicle.alamat_client:
        lines.append(f"📍 Alamat: {vehicle.alamat_client}")
    return "\n".join(lines)


def format_service_record(record: ServiceRecord) -> str:
    lines = [f"🛠️ Servis {record.waktu_service.strftime('%d/%m/%Y')}"]
    if record.jobs:
        lines.append("• Pekerjaan:")
        for job in record.jobs:
            harga = format_rupiah(job.harga) if job.harga is not None else "harga belum diketahui"
            lines.append(f"  - {job.deskripsi} (x{job.jumlah}) = {harga}")
    if record.parts:
        lines.append("• Part:")
        for part in record.parts:
            harga = (
                format_rupiah(part.harga_satuan)
                if part.harga_satuan is not None
                else "harga belum diketahui"
            )
            lines.append(f"  - {part.nama_part} (x{part.jumlah}) = {harga}")
    lines.append(f"💰 Biaya jasa: {format_rupiah(record.biaya_jasa)}")
    lines.append(f"💰 Total part: {format_rupiah(record.total_part)}")
    lines.append(f"💵 Total servis: {format_rupiah(record.total_servis)}")
    lines.append(f"🛡️ Garansi s/d: {format_date(record.garansi_sampai)}")
    lines.append(f"📋 Status klaim: {record.status_klaim}")
    return "\n".join(lines)


def warranty_is_active(record: ServiceRecord, today: date | None = None) -> bool:
    """True when the warranty end date is today or later."""
    if record.garansi_sampai is None:
        return False
    today = today or date.today()
    return record.garansi_sampai >= today


def format_warranty(record: ServiceRecord, today: date | None = None) -> str:
    state = "✅ berlaku" if warranty_is_active(record, today) else "❌ tidak berlaku"
    return (
        f"🛠️ Servis {record.waktu_service.strftime('%d/%m/%Y')}\n"
        f"  Garansi s/d: {format_date(record.garansi_sampai)} — {state}\n"
        f"  Status klaim: {record.status_klaim}"
    )
