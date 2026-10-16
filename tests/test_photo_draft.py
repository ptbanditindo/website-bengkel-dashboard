"""Deterministic tests for the photo extraction draft logic (H7B).

Uses the DAVA RADIATOR nota transcription as a controlled fixture (ground truth
for data structure and totals) — NOT a real photo or real OCR result. No API
calls. Classification of job vs part is the model's output, not asserted here.
"""

from decimal import Decimal

import bot.ai_handlers as ai_handlers

# DAVA RADIATOR nota (transcription) as an extraction fixture.
# The nota has no readable plate/customer name; those are left empty.
DAVA_DATA = {
    "plat": "",
    "nama_client": "",
    "jobs": [
        {"deskripsi": "bongkar pasang service radiator", "jumlah": 1, "harga": "Rp 575.000"},
        {"deskripsi": "jasa storing", "jumlah": 1, "harga": "Rp 200.000"},
        {"deskripsi": "service radiator coller", "jumlah": 1, "harga": "Rp 275.000"},
    ],
    "parts": [
        {"nama_part": "uppertank", "jumlah": 1, "harga_satuan": "Rp 775.000"},
    ],
    "total": "Rp 1.825.000",
    "garansi_sampai": None,
    "catatan": None,
}


def test_dava_draft_preserves_four_items():
    summary, args = ai_handlers._build_service_draft(DAVA_DATA)
    assert len(args["jobs"]) == 3
    assert len(args["parts"]) == 1
    for name in ("bongkar pasang service radiator", "jasa storing", "service radiator coller"):
        assert name in summary
    assert "uppertank" in summary


def test_dava_item_sum_is_1825000():
    assert ai_handlers._sum_item_prices(DAVA_DATA["jobs"], DAVA_DATA["parts"]) == Decimal("1825000")


def test_dava_total_matches_item_sum():
    summary, _ = ai_handlers._build_service_draft(DAVA_DATA)
    assert "cocok dengan rincian" in summary


def test_dava_total_mismatch_detected():
    mismatch = dict(DAVA_DATA, total="Rp 2.000.000")
    summary, _ = ai_handlers._build_service_draft(mismatch)
    assert "tidak cocok" in summary


def test_missing_items_draft():
    data = {
        "plat": "",
        "jobs": [{"deskripsi": "jasa storing", "jumlah": 1, "harga": "Rp 200.000"}],
        "parts": [],
    }
    summary, args = ai_handlers._build_service_draft(data)
    assert "jasa storing" in summary
    assert args["parts"] == []


def test_invalid_price_returns_none_sum():
    data = {"jobs": [{"deskripsi": "jasa storing", "jumlah": 1, "harga": "abc"}]}
    assert ai_handlers._sum_item_prices(data["jobs"], []) is None


def test_no_total_no_crosscheck_line():
    data = dict(DAVA_DATA)
    data.pop("total")
    summary, _ = ai_handlers._build_service_draft(data)
    assert "Total" not in summary


def test_parse_money_handles_nota_formats():
    assert ai_handlers._coerce_money("Rp 575.000") == Decimal("575000.00")
    assert ai_handlers._coerce_money("Rp 1.825.000") == Decimal("1825000.00")
    assert ai_handlers._coerce_money("abc") is None
    assert ai_handlers._coerce_money(None) is None
