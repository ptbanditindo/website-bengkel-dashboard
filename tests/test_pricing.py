"""Tests for the pure money-calculation and validation helpers."""

from decimal import Decimal

import pytest

from services.exceptions import ValidationError
from services.pricing import grand_total, item_subtotal, parse_money, to_decimal, total_of
from services.validation import validate_price, validate_quantity, validate_tahun


def test_to_decimal_none():
    assert to_decimal(None) is None


def test_to_decimal_rounds_to_two_places():
    assert to_decimal("150000") == Decimal("150000.00")
    assert to_decimal(850000) == Decimal("850000.00")


def test_item_subtotal():
    assert item_subtotal(2, Decimal("50000")) == Decimal("100000.00")


def test_item_subtotal_unknown_price_is_none():
    assert item_subtotal(2, None) is None


def test_total_of_empty_is_zero():
    assert total_of([]) == Decimal("0")


def test_total_of_complete():
    assert total_of([Decimal("100000.00"), Decimal("200000.00")]) == Decimal("300000.00")


def test_total_of_incomplete_is_none():
    assert total_of([Decimal("100000.00"), None]) is None


def test_grand_total():
    assert grand_total(Decimal("150000.00"), Decimal("950000.00")) == Decimal("1100000.00")


def test_grand_total_incomplete_is_none():
    assert grand_total(None, Decimal("950000.00")) is None


def test_validate_quantity_rejects_zero_and_negative():
    with pytest.raises(ValidationError):
        validate_quantity(0)
    with pytest.raises(ValidationError):
        validate_quantity(-1)


def test_validate_quantity_accepts_int_and_str():
    assert validate_quantity(2) == 2
    assert validate_quantity("2") == 2


def test_validate_price_rejects_negative():
    with pytest.raises(ValidationError):
        validate_price(-50000)


def test_validate_price_accepts_none_and_values():
    assert validate_price(None) is None
    assert validate_price("850000") == Decimal("850000.00")


def test_validate_tahun_rejects_impossible():
    with pytest.raises(ValidationError):
        validate_tahun(1800)
    with pytest.raises(ValidationError):
        validate_tahun(9999)


def test_parse_money_plain_number():
    assert parse_money("150000") == Decimal("150000.00")
    assert parse_money(850000) == Decimal("850000.00")
    assert parse_money(Decimal("50000")) == Decimal("50000.00")


def test_parse_money_rb_suffix():
    assert parse_money("600rb") == Decimal("600000.00")
    assert parse_money("600 ribu") == Decimal("600000.00")


def test_parse_money_juta():
    assert parse_money("1,5 juta") == Decimal("1500000.00")
    assert parse_money("2jt") == Decimal("2000000.00")
    assert parse_money("2 juta") == Decimal("2000000.00")


def test_parse_money_rp_prefix():
    assert parse_money("Rp600.000") == Decimal("600000.00")


def test_parse_money_decimal_comma():
    assert parse_money("1,5") == Decimal("1.50")


def test_parse_money_none_and_empty():
    assert parse_money(None) is None
    assert parse_money("") is None


def test_parse_money_invalid():
    with pytest.raises(Exception):
        parse_money("abc")


def test_validate_price_accepts_indonesian_formats():
    assert validate_price("600rb") == Decimal("600000.00")
    assert validate_price("Rp600.000") == Decimal("600000.00")
    assert validate_price("1,5 juta") == Decimal("1500000.00")
