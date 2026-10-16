"""Input parsing helpers for the structured (pre-AI) Telegram flow."""

import re
from datetime import date

from services.exceptions import ValidationError

# Indonesian plate shape: 1-2 letters, 1-4 digits, 1-3 letters (e.g. "M 3144 VVV").
_PLATE_RE = re.compile(r"\b([A-Za-z]{1,2})\s*(\d{1,4})\s*([A-Za-z]{1,3})\b")


def extract_plate(text: str) -> str | None:
    """Extract the first plate-like token from free text, or ``None``."""
    m = _PLATE_RE.search(text or "")
    if not m:
        return None
    return " ".join(part for part in m.groups() if part)


def parse_item_lines(text: str) -> list[tuple[str, str, str | None]]:
    """Parse multi-line ``name|qty|price`` text into ``(name, qty, price)``.

    ``qty`` defaults to ``"1"`` and ``price`` may be ``None`` when omitted.
    """
    result = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        fields = [f.strip() for f in line.split("|")]
        name = fields[0]
        qty = fields[1] if len(fields) > 1 and fields[1] else "1"
        price = fields[2] if len(fields) > 2 and fields[2] else None
        result.append((name, qty, price))
    return result


def parse_optional_date(text: str) -> date | None:
    """Parse an optional ``YYYY-MM-DD`` date; ``None`` for empty or ``-``."""
    text = (text or "").strip()
    if not text or text == "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ValidationError(f"Format tanggal tidak valid: {text}. Gunakan YYYY-MM-DD.")
