from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class SalesInvoice(Base, AuditMixin):
    __tablename__ = "sales_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    taxable_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    cgst: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    sgst: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    igst: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    # Patch v1.1.0 (migration 002): how often the invoice was edited and when
    # last. Must equal the number of sales_invoice_audit rows for it.
    edit_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    last_edited_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped["Customer"] = relationship(back_populates="invoices")
    items: Mapped[list["SalesInvoiceItem"]] = relationship(back_populates="invoice")
