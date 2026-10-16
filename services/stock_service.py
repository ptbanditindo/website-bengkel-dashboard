"""Stock service: CRUD for stock items (spare parts with cost, price & quantity)."""

from sqlalchemy.orm import Session

from database.models import ServicePart, StockItem
from services.exceptions import ConflictError, NotFoundError, ValidationError
from services.validation import clean_required, validate_price


def _validate_qty(value):
    if isinstance(value, bool):
        raise ValidationError("Jumlah stok harus angka bulat.")
    try:
        qty = int(value)
    except (ValueError, TypeError):
        raise ValidationError(f"Jumlah stok tidak valid: {value}.")
    if qty < 0:
        raise ValidationError("Jumlah stok tidak boleh negatif.")
    return qty


class StockService:
    def __init__(self, session: Session):
        self._session = session

    def list_items(self) -> list[StockItem]:
        return list(self._session.query(StockItem).order_by(StockItem.nama.asc()).all())

    def get_item(self, item_id: int) -> StockItem:
        item = self._session.get(StockItem, item_id)
        if item is None:
            raise NotFoundError(f"Stok dengan id {item_id} tidak ditemukan.")
        return item

    def _find_by_kode(self, kode):
        kode = (kode or "").strip() or None
        if kode is None:
            return None
        return self._session.query(StockItem).filter(StockItem.kode == kode).first()

    def _check_kode_unique(self, kode, exclude_id=None):
        existing = self._find_by_kode(kode)
        if existing is not None and existing.id != exclude_id:
            raise ConflictError(f"Kode stok {kode} sudah dipakai.")

    def create_item(self, nama, kode=None, harga_modal=None, harga_jual=None, jumlah=0, commit=True) -> StockItem:
        kode = (kode or "").strip() or None
        self._check_kode_unique(kode)
        item = StockItem(
            kode=kode,
            nama=clean_required(nama, "Nama barang"),
            harga_modal=validate_price(harga_modal),
            harga_jual=validate_price(harga_jual),
            jumlah=_validate_qty(jumlah),
        )
        self._session.add(item)
        if commit:
            self._session.commit()
        else:
            self._session.flush()
        return item

    def update_item(self, item_id: int, commit=True, **changes) -> StockItem:
        item = self.get_item(item_id)
        if "kode" in changes:
            kode = (changes["kode"] or "").strip() or None
            self._check_kode_unique(kode, exclude_id=item.id)
            item.kode = kode
        if "nama" in changes:
            item.nama = clean_required(changes["nama"], "Nama barang")
        if "harga_modal" in changes:
            item.harga_modal = validate_price(changes["harga_modal"])
        if "harga_jual" in changes:
            item.harga_jual = validate_price(changes["harga_jual"])
        if "jumlah" in changes:
            item.jumlah = _validate_qty(changes["jumlah"])
        if commit:
            self._session.commit()
        else:
            self._session.flush()
        return item

    def delete_item(self, item_id: int, commit=True) -> None:
        item = self.get_item(item_id)
        referenced = (
            self._session.query(ServicePart)
            .filter(ServicePart.stock_item_id == item_id)
            .count()
        )
        if referenced > 0:
            raise ConflictError(
                f"Stok {item.nama} tidak bisa dihapus karena dipakai di {referenced} riwayat servis."
            )
        self._session.delete(item)
        if commit:
            self._session.commit()
        else:
            self._session.flush()

    def adjust_stock(self, item_id: int, delta: int, commit=True) -> StockItem:
        """Increase or decrease stock quantity by delta (used by service parts)."""
        item = self.get_item(item_id)
        new_qty = item.jumlah + int(delta)
        if new_qty < 0:
            raise ConflictError(f"Stok {item.nama} tidak cukup.")
        item.jumlah = new_qty
        if commit:
            self._session.commit()
        else:
            self._session.flush()
        return item
