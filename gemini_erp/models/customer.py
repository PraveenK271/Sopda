from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class Customer(Base, AuditMixin):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    invoices: Mapped[list["SalesInvoice"]] = relationship(back_populates="customer")
    ledger_account: Mapped["LedgerAccount | None"] = relationship(back_populates="customer", uselist=False)
