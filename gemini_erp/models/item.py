from __future__ import annotations

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class Item(Base, AuditMixin):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hsn_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gst_rate: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    opening_stock: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    reorder_level: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    stock_transactions: Mapped[list["StockTransaction"]] = relationship(back_populates="item")
    sale_lines: Mapped[list["SalesInvoiceItem"]] = relationship(back_populates="item")
    purchase_lines: Mapped[list["PurchaseInvoiceItem"]] = relationship(back_populates="item")
