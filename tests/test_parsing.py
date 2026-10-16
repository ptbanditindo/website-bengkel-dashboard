"""Tests for structured input parsing helpers."""

from datetime import date

import pytest

from bot.parsing import parse_item_lines, parse_optional_date
from services.exceptions import ValidationError


def test_parse_item_lines_single():
    assert parse_item_lines("Pasang radiator|1|150000") == [("Pasang radiator", "1", "150000")]


def test_parse_item_lines_multiple():
    text = "Radiator|1|850000\nAir radiator|2|50000"
    assert parse_item_lines(text) == [
        ("Radiator", "1", "850000"),
        ("Air radiator", "2", "50000"),
    ]


def test_parse_item_lines_defaults_qty_and_price():
    assert parse_item_lines("Ganti oli") == [("Ganti oli", "1", None)]
    assert parse_item_lines("Ganti oli|2") == [("Ganti oli", "2", None)]


def test_parse_item_lines_ignores_blank_lines():
    assert parse_item_lines("A|1|2\n\nB|1|3\n") == [("A", "1", "2"), ("B", "1", "3")]


def test_parse_optional_date_valid():
    assert parse_optional_date("2027-01-14") == date(2027, 1, 14)


def test_parse_optional_date_dash_and_empty():
    assert parse_optional_date("-") is None
    assert parse_optional_date("") is None


def test_parse_optional_date_invalid():
    with pytest.raises(ValidationError):
        parse_optional_date("14/01/2027")
