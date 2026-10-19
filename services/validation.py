"""Input validation helpers shared by the service layer."""

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from database.models import CLAIM_STATUSES, normalize_plate
from services.exceptions import ValidationError
from services.pricing import parse_money


def clean_required(value, field_name: str) -> str:
    if value is None:
        raise ValidationError(f"{field_name} wajib diisi.")
    text = str(value).strip()
    if not text:
        raise ValidationError(f"{field_name} wajib diisi.")
    return text


def clean_optional(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_required_plate(nopol: str) -> str:
    normalized = normalize_plate(nopol)
    if not normalized:
        raise ValidationError("Nomor polisi tidak boleh kosong.")
    return normalized


def validate_tahun(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValidationError("Tahun mobil harus berupa angka.")
    if isinstance(value, int):
        year = value
    elif isinstance(value, str):
        try:
            year = int(value.strip())
        except ValueError:
            raise ValidationError(f"Tahun mobil tidak valid: {value}.")
    else:
        raise ValidationError("Tahun mobil harus berupa angka.")

    current = datetime.now().year
    if year < 1900 or year > current + 1:
        raise ValidationError(f"Tahun mobil tidak valid: {year}.")
    return year


def validate_quantity(value) -> int:
    if isinstance(value, bool):
        raise ValidationError("Jumlah harus berupa angka bulat positif.")
    if isinstance(value, int):
        qty = value
    elif isinstance(value, str):
        try:
            qty = int(value.strip())
        except ValueError:
            raise ValidationError(f"Jumlah tidak valid: {value}.")
    else:
        raise ValidationError("Jumlah harus berupa angka bulat positif.")

    if qty < 1:
        raise ValidationError("Jumlah harus lebih dari 0.")
    return qty


def validate_price(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValidationError("Harga harus berupa angka.")
    try:
        d = parse_money(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(f"Harga tidak valid: {value}.")
    if d is None:
        return None
    if d < 0:
        raise ValidationError("Harga tidak boleh negatif.")
    return d


def validate_status_klaim(status: str) -> str:
    if status not in CLAIM_STATUSES:
        raise ValidationError(f"Status klaim tidak valid: {status}.")
    return status


# Waktu Indonesia Barat (UTC+7) — no DST, so a fixed offset matches Asia/Jakarta.
WIB = timezone(timedelta(hours=7))

_RELATIVE_DAYS = {
    "hari ini": 0,
    "today": 0,
    "kemarin": -1,
    "kemaren": -1,
    "yesterday": -1,
    "besok": 1,
    "tomorrow": 1,
}

_DURATION_RE = re.compile(r"^\s*(\d+)\s*(hari|minggu|bulan|tahun)\s*$")

_MONTH_NAMES = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "agu": 8, "ags": 8, "sep": 9, "okt": 10, "nov": 11, "des": 12,
}

_NAMED_MONTH_RE = re.compile(r"^\s*(\d{1,2})?\s*([a-zA-Z]+)\s*(\d{4})?\s*$")


def _today_wib() -> date:
    """Return today's date in the workshop timezone (WIB)."""
    return datetime.now(WIB).date()


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def parse_date_expression(text: str) -> date:
    """Resolve a relative or explicit Indonesian date expression to a ``date``.

    Supports ``hari ini`` / ``kemarin`` / ``besok``, ``N hari|minggu|bulan|tahun``,
    ISO ``YYYY-MM-DD``, and ``DD-MM-YYYY`` / ``DD/MM/YYYY``. Uses the local WIB
    clock for relative dates so ``hari ini`` never depends on the AI model's
    knowledge of the current date.
    """
    s = (text or "").strip()
    key = s.lower()

    rel = _RELATIVE_DAYS.get(key)
    if rel is not None:
        return _today_wib() + timedelta(days=rel)

    m = _DURATION_RE.match(key)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        today = _today_wib()
        if unit == "hari":
            return today + timedelta(days=n)
        if unit == "minggu":
            return today + timedelta(weeks=n)
        if unit == "bulan":
            return _add_months(today, n)
        return _add_months(today, n * 12)  # tahun

    # "2 agustus 2027" / "2 agustus" / "agustus 2027" (nama bulan Indonesia).
    m = _NAMED_MONTH_RE.match(key)
    if m:
        month = _MONTH_NAMES.get(m.group(2))
        if month is not None:
            year = int(m.group(3)) if m.group(3) else _today_wib().year
            day = int(m.group(1)) if m.group(1) else 1
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # ISO YYYY-MM-DD.
    try:
        return date.fromisoformat(s)
    except ValueError:
        pass

    # DD-MM-YYYY / DD/MM/YYYY (and YYYY/MM/DD).
    for sep in ("-", "/"):
        parts = s.split(sep)
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            if len(parts[0]) == 4:
                y, m_, d_ = int(parts[0]), int(parts[1]), int(parts[2])
            else:
                d_, m_, y = int(parts[0]), int(parts[1]), int(parts[2])
            try:
                return date(y, m_, d_)
            except ValueError:
                break

    raise ValidationError(
        f"Format tanggal tidak valid: {text}. Gunakan YYYY-MM-DD, DD-MM-YYYY, 'hari ini', atau '2 Agustus 2026'."
    )


def coerce_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s or s == "-":
            return None
        return parse_date_expression(s)
    raise ValidationError(f"Format tanggal tidak valid: {value}.")


def normalize_warranty(bergaransi, garansi_sampai):
    """Resolve warranty fields per the 'garansi wajib diisi' rule.

    Returns ``(bergaransi, garansi_sampai)`` where ``bergaransi`` is
    ``True``/``False``/``None`` (``None`` = belum diisi) and ``garansi_sampai``
    is a ``date`` or ``None``.
    """
    d = coerce_date(garansi_sampai)
    if bergaransi is True:
        if d is None:
            raise ValidationError("Tanggal garansi wajib diisi jika bergaransi.")
        return True, d
    if bergaransi is False:
        return False, None
    return (True, d) if d is not None else (None, None)


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def coerce_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _to_naive_utc(value)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        s = value.strip()
        if not s or s == "-":
            return None
        try:
            d = parse_date_expression(s)  # relative or plain date -> midnight
            return datetime(d.year, d.month, d.day)
        except ValidationError:
            pass
        try:
            return _to_naive_utc(datetime.fromisoformat(s.replace("Z", "+00:00")))
        except ValueError:
            raise ValidationError(f"Format tanggal/waktu tidak valid: {value}.")
    raise ValidationError(f"Format tanggal/waktu tidak valid: {value}.")
