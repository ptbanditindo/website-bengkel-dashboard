"""Harga jasa service: CRUD for service price-list entries (labour profit)."""

from sqlalchemy.orm import Session

from database.models import HargaJasa
from services.exceptions import NotFoundError
from services.validation import clean_required, validate_price


class HargaJasaService:
    def __init__(self, session: Session):
        self._session = session

    def list_items(self) -> list[HargaJasa]:
        return list(self._session.query(HargaJasa).order_by(HargaJasa.nama.asc()).all())

    def get_item(self, item_id: int) -> HargaJasa:
        item = self._session.get(HargaJasa, item_id)
        if item is None:
            raise NotFoundError(f"Harga jasa dengan id {item_id} tidak ditemukan.")
        return item

    def create_item(self, nama, keuntungan=None, commit=True) -> HargaJasa:
        item = HargaJasa(
            nama=clean_required(nama, "Nama jasa"),
            keuntungan=validate_price(keuntungan),
        )
        self._session.add(item)
        if commit:
            self._session.commit()
        else:
            self._session.flush()
        return item

    def update_item(self, item_id: int, commit=True, **changes) -> HargaJasa:
        item = self.get_item(item_id)
        if "nama" in changes:
            item.nama = clean_required(changes["nama"], "Nama jasa")
        if "keuntungan" in changes:
            item.keuntungan = validate_price(changes["keuntungan"])
        if commit:
            self._session.commit()
        else:
            self._session.flush()
        return item

    def delete_item(self, item_id: int, commit=True) -> None:
        item = self.get_item(item_id)
        self._session.delete(item)
        if commit:
            self._session.commit()
        else:
            self._session.flush()
