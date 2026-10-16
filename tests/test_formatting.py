"""Tests for pure formatting helpers."""

from datetime import date, datetime
from decimal import Decimal

from bot.formatting import (
    format_rupiah,
    format_service_record,
    format_vehicle,
    format_warranty,
    warranty_is_active,
)
from database.models import ServiceJob, ServicePart, ServiceRecord, Vehicle


def test_format_rupiah():
    assert format_rupiah(850000) == "Rp850.000"
    assert format_rupiah(None) == "belum diketahui"


def test_format_vehicle():
    v = Vehicle(
        nama_client="Budi",
        nopol="B1234ABC",
        jenis_mobil="Toyota Avanza",
        tahun_mobil=2020,
    )
    text = format_vehicle(v)
    assert "B1234ABC" in text
    assert "Budi" in text
    assert "Toyota Avanza" in text
    assert "2020" in text


def test_format_service_record():
    record = ServiceRecord(
        waktu_service=datetime(2027, 1, 10),
        biaya_jasa=Decimal("150000.00"),
        total_part=Decimal("950000.00"),
        total_servis=Decimal("1100000.00"),
        garansi_sampai=date(2027, 1, 14),
        status_klaim="Belum claim",
    )
    record.jobs = [ServiceJob(deskripsi="Pasang radiator", jumlah=1, harga=Decimal("150000"))]
    record.parts = [ServicePart(nama_part="Radiator", jumlah=1, harga_satuan=Decimal("850000"))]
    text = format_service_record(record)
    assert "Pasang radiator" in text
    assert "Radiator" in text
    assert "Rp1.100.000" in text
    assert "Belum claim" in text


def test_warranty_is_active():
    record = ServiceRecord(garansi_sampai=date(2027, 1, 14))
    assert warranty_is_active(record, today=date(2027, 1, 1)) is True
    assert warranty_is_active(record, today=date(2027, 1, 15)) is False


def test_warranty_is_active_when_no_date():
    record = ServiceRecord(garansi_sampai=None)
    assert warranty_is_active(record) is False


def test_format_warranty():
    record = ServiceRecord(
        waktu_service=datetime(2027, 1, 10),
        garansi_sampai=date(2027, 1, 14),
        status_klaim="Belum claim",
    )
    text = format_warranty(record, today=date(2027, 1, 1))
    assert "berlaku" in text
    assert "Belum claim" in text
