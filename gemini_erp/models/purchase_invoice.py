from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Date, ForeignKey, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class PurchaseInvoice(Base, AuditMixin):
    __tablename__ = "purchase_invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Supplier's own invoice number - unlike SalesInvoice.invoice_no this is
    # not globally unique (different suppliers can reuse the same number).
    invoice_no: Mapped[str] = mapped_column(String(50), nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    taxable_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    cgst: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    sgst: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    igst: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    # Patch v1.1.0 (migration 001). A flat rupee discount off the whole bill,
    # apportioned across the lines BEFORE GST. Default 0 keeps every pre-patch
    # bill computing exactly as it did.
    special_discount: Mapped[float] = mapped_column(
        Numeric(15, 2), default=0, server_default=text("0"), nullable=False
    )
    # Line discounts + special discount, stored only for reporting.
    total_discount: Mapped[float] = mapped_column(
        Numeric(15, 2), default=0, server_default=text("0"), nullable=False
    )

    supplier: Mapped["Supplier"] = relationship(back_populates="purchase_invoices")
    items: Mapped[list["PurchaseInvoiceItem"]] = relationship(back_populates="invoice")
