from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class Supplier(Base, AuditMixin):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    purchase_invoices: Mapped[list["PurchaseInvoice"]] = relationship(back_populates="supplier")
    ledger_account: Mapped["LedgerAccount | None"] = relationship(back_populates="supplier", uselist=False)
