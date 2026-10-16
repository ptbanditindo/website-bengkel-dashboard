"""Catalog cross-check helpers.

Match job/part descriptions against the ``HargaJasa`` (service price list) and
``StockItem`` (parts) catalogues, so the UI/bot can warn the owner when an
entered price differs from the known price.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from database.models import HargaJasa, StockItem
from services.pricing import parse_money


def _norm(name) -> str:
    return " ".join((name or "").lower().split())


def find_harga_jasa(session: Session, name) -> HargaJasa | None:
    """Find a service price-list entry by (normalized) name.

    Exact match wins; otherwise the best substring match (query inside catalog
    name or catalog name inside query) is returned.
    """
    q = _norm(name)
    if not q:
        return None
    items = session.query(HargaJasa).all()
    exact = [i for i in items if _norm(i.nama) == q]
    if exact:
        return exact[0]
    subs = [i for i in items if q in _norm(i.nama) or _norm(i.nama) in q]
    if subs:
        return max(subs, key=lambda i: len(_norm(i.nama)))
    return None


def find_stock_item(session: Session, name) -> StockItem | None:
    """Find a stock item by normalized name or code."""
    q = _norm(name)
    if not q:
        return None
    items = session.query(StockItem).all()
    for i in items:
        if _norm(i.nama) == q or (i.kode and _norm(i.kode) == q):
            return i
    subs = [i for i in items if q in _norm(i.nama) or _norm(i.nama) in q]
    if subs:
        return max(subs, key=lambda i: len(_norm(i.nama)))
    return None


def _fmt(amount) -> str:
    if amount is None:
        return "-"
    return f"{int(amount):,}".replace(",", ".")


def catalog_price_warnings(session: Session, jobs, parts) -> list[str]:
    """Return human-readable warnings for jobs/parts whose price differs from the catalogue.

    ``jobs`` and ``parts`` are the raw dict lists (``deskripsi``/``harga`` and
    ``nama_part``/``harga_satuan``) as produced by the AI or the structured flow.
    A warning is emitted only when a catalogue entry is found and its price is
    known; it never blocks saving.
    """
    warnings = []

    for j in jobs or []:
        deskripsi = (j.get("deskripsi") or "").strip()
        entry = find_harga_jasa(session, deskripsi)
        if entry is None or entry.keuntungan is None:
            continue
        try:
            harga = parse_money(j.get("harga"))
        except Exception:
            harga = None
        if harga is None:
            warnings.append(f"⚠️ \"{deskripsi}\": harga belum diisi — katalog Rp{_fmt(entry.keuntungan)}")
        elif harga != entry.keuntungan:
            warnings.append(
                f"⚠️ \"{deskripsi}\": input Rp{_fmt(harga)} ≠ katalog Rp{_fmt(entry.keuntungan)}"
            )

    for p in parts or []:
        nama = (p.get("nama_part") or "").strip()
        entry = find_stock_item(session, nama)
        if entry is None or entry.harga_jual is None:
            continue
        try:
            harga = parse_money(p.get("harga_satuan"))
        except Exception:
            harga = None
        if harga is None:
            warnings.append(f"⚠️ \"{nama}\": harga belum diisi — katalog stok Rp{_fmt(entry.harga_jual)}")
        elif harga != entry.harga_jual:
            warnings.append(
                f"⚠️ \"{nama}\": input Rp{_fmt(harga)} ≠ katalog stok Rp{_fmt(entry.harga_jual)}"
            )

    return warnings


def _as_money(value):
    """Return an ``int`` for whole amounts (cleaner display), else ``Decimal``."""
    d = Decimal(value)
    return int(d) if d == d.to_integral_value() else d


def find_stock_item_by_price(session: Session, price, hint=None) -> StockItem | None:
    """Find a stock item whose sell price equals ``price``.

    When several items share the price, prefer the one whose name overlaps the
    ``hint`` (e.g. the job description); if still ambiguous, return ``None`` so
    callers do not guess.
    """
    if price is None:
        return None
    items = session.query(StockItem).filter(StockItem.harga_jual == price).all()
    if not items:
        return None
    if len(items) == 1:
        return items[0]
    hint_tokens = set(_norm(hint).split())
    for item in items:
        if hint_tokens & set(_norm(item.nama).split()):
            return item
    return None


def split_job_into_service_and_part(session: Session, job):
    """Try to split a job price into catalogue service + matching stock part.

    Only splits when the entered price is *higher* than the matched
    ``HargaJasa`` price and the difference equals a stock item's sell price.
    Returns ``(adjusted_job, new_part)`` or ``None`` when no split is possible.
    """
    deskripsi = (job.get("deskripsi") or "").strip()
    entry = find_harga_jasa(session, deskripsi)
    if entry is None or entry.keuntungan is None:
        return None
    try:
        harga = parse_money(job.get("harga"))
    except Exception:
        return None
    if harga is None or harga <= entry.keuntungan:
        return None
    diff = harga - entry.keuntungan
    part = find_stock_item_by_price(session, diff, hint=deskripsi)
    if part is None or part.harga_jual is None:
        return None

    adjusted = dict(job)
    adjusted["harga"] = _as_money(entry.keuntungan)
    new_part = {
        "nama_part": part.nama,
        "jumlah": job.get("jumlah", 1),
        "harga_satuan": _as_money(part.harga_jual),
    }
    return adjusted, new_part


def apply_auto_split(session: Session, jobs, parts):
    """Auto-split splittable jobs, returning ``(notes, new_jobs, new_parts)``."""
    notes = []
    new_jobs = []
    new_parts = list(parts or [])
    for job in jobs or []:
        result = split_job_into_service_and_part(session, job)
        if result is None:
            new_jobs.append(job)
            continue
        adjusted, new_part = result
        new_jobs.append(adjusted)
        new_parts.append(new_part)
        notes.append(
            f"ℹ️ \"{adjusted['deskripsi']}\" dipecah otomatis: "
            f"jasa Rp{_fmt(adjusted['harga'])} + part \"{new_part['nama_part']}\" Rp{_fmt(new_part['harga_satuan'])}"
        )
    return notes, new_jobs, new_parts
