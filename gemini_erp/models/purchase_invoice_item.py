from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class PurchaseInvoiceItem(Base, AuditMixin):
    __tablename__ = "purchase_invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("purchase_invoices.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    rate: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # The line's TAXABLE value: quantity x rate, less its line discount, less its
    # apportioned share of the invoice's special discount. Registers read this
    # column, so they show net (post-discount) figures automatically. On a
    # pre-patch row (no discounts) it is simply quantity x rate, as before.
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    gst_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    # Patch v1.1.0 (migration 001): the supplier's per-line trade discount.
    # discount_amount is the percentage discount only; the special-discount
    # share is (quantity x rate) - discount_amount - amount.
    discount_percent: Mapped[float] = mapped_column(
        Numeric(5, 2), default=0, server_default=text("0"), nullable=False
    )
    discount_amount: Mapped[float] = mapped_column(
        Numeric(15, 2), default=0, server_default=text("0"), nullable=False
    )

    invoice: Mapped["PurchaseInvoice"] = relationship(back_populates="items")
    item: Mapped["Item"] = relationship(back_populates="purchase_lines")
