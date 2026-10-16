"""Money calculation helpers.

All financial arithmetic lives here (never delegated to an AI) and uses
``decimal.Decimal`` with a consistent two-decimal rounding rule so that
subtotals and totals are exact.
"""

import re
from decimal import Decimal, ROUND_HALF_UP

MONEY_PLACES = Decimal("0.01")

# Indonesian money-word suffixes -> multiplier (longest first so "juta" wins over "jt").
_MONEY_MULTIPLIERS = (
    ("miliar", Decimal("1000000000")),
    ("milyar", Decimal("1000000000")),
    ("juta", Decimal("1000000")),
    ("jt", Decimal("1000000")),
    ("ribu", Decimal("1000")),
    ("rb", Decimal("1000")),
    ("k", Decimal("1000")),  # "470k" -> 470000
)


def to_decimal(value) -> Decimal | None:
    """Coerce a value to a 2-decimal ``Decimal``; return ``None`` for ``None``."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def parse_money(value) -> Decimal | None:
    """Parse an Indonesian money expression into a 2-decimal ``Decimal``.

    Understands ``600rb``, ``Rp600.000``, ``1,5 juta``, ``150000``, plain
    ``int``/``float``/``Decimal``, and already-Decimal values. Returns ``None``
    for ``None``/empty input. Raises ``ValueError``/``decimal.InvalidOperation``
    for unparseable input (callers translate this to a validation error).

    The meaning of a nominal (total vs. jasa vs. part) is never guessed here;
    this only normalizes the number itself.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("uang tidak boleh boolean")
    if isinstance(value, (int, float, Decimal)):
        return to_decimal(value)

    text = str(value).strip()
    if not text:
        return None

    t = text.lower().replace("rp", "").replace("idr", "").strip()
    multiplier = Decimal("1")

    for word, mult in _MONEY_MULTIPLIERS:
        if t.endswith(word):
            # attached suffix: "600rb", "2jt", "1,5juta"
            multiplier = mult
            t = t[: -len(word)]
            break
        if re.search(rf"(^|\s){word}($|\s)", t):
            # standalone word: "600 ribu", "1,5 juta"
            multiplier = mult
            t = re.sub(rf"(^|\s){word}($|\s)", " ", t)
            break

    t = t.replace(" ", "").replace("_", "")
    if not t:
        raise ValueError(f"nominal tidak valid: {value}")

    # Indonesian convention: '.' separates thousands, ',' is the decimal point.
    if "," in t and "." in t:
        # e.g. "1.500.000,50" -> "1500000.50"
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        if re.fullmatch(r"\d{1,3}(,\d{1,2})?", t):
            t = t.replace(",", ".")  # "1,5" -> "1.5"
        else:
            t = t.replace(",", "")  # "1,500,000" -> "1500000"
    elif "." in t:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
            t = t.replace(".", "")  # "600.000" -> "600000"
        # otherwise keep the decimal point ("1.5")

    d = Decimal(t)
    return (d * multiplier).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def item_subtotal(jumlah: int, harga: Decimal | None) -> Decimal | None:
    """``subtotal = jumlah * harga``; ``None`` when the unit price is unknown."""
    if harga is None:
        return None
    return (Decimal(jumlah) * harga).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def total_of(subtotals: list[Decimal | None]) -> Decimal | None:
    """Sum subtotals.

    Returns ``Decimal("0")`` for an empty list, and ``None`` when any item is
    unknown (so an incomplete total is never presented as a real value).
    """
    if not subtotals:
        return Decimal("0").quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
    if any(s is None for s in subtotals):
        return None
    return sum(subtotals, Decimal("0")).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def grand_total(biaya_jasa: Decimal | None, total_part: Decimal | None) -> Decimal | None:
    """Total = biaya_jasa + total_part; ``None`` when either component is unknown."""
    if biaya_jasa is None or total_part is None:
        return None
    return (biaya_jasa + total_part).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)
