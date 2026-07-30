from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class StockTransaction(Base, AuditMixin):
    __tablename__ = "stock_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(3), nullable=False)  # 'IN' or 'OUT'
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. 'SALE'
    reference_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # Transaction date mirrors the source document's date (a calendar date, like
    # every other business-date column). It was previously DateTime, which the
    # MSSQL driver rejects when handed a plain date; Date matches the value that
    # is actually stored and stays consistent with sales/purchase/journal dates.
    date: Mapped[date_type] = mapped_column(Date, default=date_type.today)

    item: Mapped["Item"] = relationship(back_populates="stock_transactions")
