"""Tests for catalog price cross-check helpers."""

from decimal import Decimal

from database.models import HargaJasa, StockItem
from services.catalog import (
    apply_auto_split,
    catalog_price_warnings,
    find_harga_jasa,
    find_stock_item,
    split_job_into_service_and_part,
)


def _seed(session):
    session.add(HargaJasa(nama="Ganti oli", keuntungan=Decimal("150000")))
    session.add(HargaJasa(nama="Tune up", keuntungan=Decimal("250000")))
    session.add(StockItem(nama="Oli mesin", kode="OLI-01", harga_jual=Decimal("75000")))
    session.commit()


def test_find_harga_jasa_exact_and_substring(session):
    _seed(session)
    assert find_harga_jasa(session, "ganti oli").nama == "Ganti oli"
    assert find_harga_jasa(session, "ganti oli mesin").nama == "Ganti oli"  # substring
    assert find_harga_jasa(session, "cuci mobil") is None


def test_find_stock_item_by_name_and_kode(session):
    _seed(session)
    assert find_stock_item(session, "oli mesin").nama == "Oli mesin"
    assert find_stock_item(session, "OLI-01").nama == "Oli mesin"
    assert find_stock_item(session, "bearing") is None


def test_catalog_price_warnings_flags_mismatch(session):
    _seed(session)
    jobs = [{"deskripsi": "Ganti oli", "jumlah": 1, "harga": "50k"}]
    parts = [{"nama_part": "Oli mesin", "jumlah": 1, "harga_satuan": "75000"}]
    warnings = catalog_price_warnings(session, jobs, parts)
    # Only the job price mismatches; the part price matches its catalogue.
    assert len(warnings) == 1
    assert "Ganti oli" in warnings[0]
    assert "150.000" in warnings[0]


def test_catalog_price_warnings_no_warning_when_price_matches(session):
    _seed(session)
    jobs = [{"deskripsi": "Ganti oli", "jumlah": 1, "harga": "150000"}]
    assert catalog_price_warnings(session, jobs, []) == []


def test_split_job_into_service_and_part(session):
    session.add(HargaJasa(nama="Ganti oli", keuntungan=Decimal("150000")))
    session.add(StockItem(nama="Oli mesin", kode="OLI-01", harga_jual=Decimal("250000")))
    session.commit()
    adjusted, part = split_job_into_service_and_part(
        session, {"deskripsi": "Ganti oli", "jumlah": 1, "harga": "400k"}
    )
    assert adjusted["harga"] == 150000
    assert part["nama_part"] == "Oli mesin"
    assert part["harga_satuan"] == 250000


def test_split_job_no_matching_part(session):
    session.add(HargaJasa(nama="Ganti oli", keuntungan=Decimal("150000")))
    session.add(StockItem(nama="Ban", harga_jual=Decimal("650000")))
    session.commit()
    assert split_job_into_service_and_part(
        session, {"deskripsi": "Ganti oli", "jumlah": 1, "harga": "400k"}
    ) is None


def test_split_job_below_catalog_no_split(session):
    session.add(HargaJasa(nama="Ganti oli", keuntungan=Decimal("150000")))
    session.commit()
    assert split_job_into_service_and_part(
        session, {"deskripsi": "Ganti oli", "jumlah": 1, "harga": "50k"}
    ) is None


def test_apply_auto_split_notes(session):
    session.add(HargaJasa(nama="Ganti oli", keuntungan=Decimal("150000")))
    session.add(StockItem(nama="Oli mesin", harga_jual=Decimal("250000")))
    session.commit()
    jobs = [{"deskripsi": "Ganti oli", "jumlah": 1, "harga": "400k"}]
    notes, new_jobs, new_parts = apply_auto_split(session, jobs, [])
    assert len(notes) == 1
    assert new_jobs[0]["harga"] == 150000
    assert new_parts[0]["nama_part"] == "Oli mesin"
