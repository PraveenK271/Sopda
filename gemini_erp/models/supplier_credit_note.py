from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class SupplierCreditNote(Base, AuditMixin):
    """A credit note RECEIVED from a supplier as a discount (patch v1.1.0, P4).

    note_type decides the books: a 'GST' note (Section 34) reverses input tax,
    a 'COMMERCIAL' note carries no GST and touches no GST ledger. It has no
    default on purpose — recording one as the other misstates ITC.

    Discounts only: this never touches stock. Goods physically returned belong
    in Purchase Return.
    """

    __tablename__ = "supplier_credit_notes"
    # The supplier's own numbering: two suppliers may legitimately both issue
    # a note "CN-1", so uniqueness is per supplier, not global.
    __table_args__ = (
        UniqueConstraint("supplier_id", "credit_note_no", name="uq_supplier_credit_note_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credit_note_no: Mapped[str] = mapped_column(String(50), nullable=False)
    # Date, not DateTime: a business date like every other document date here
    # (the MSSQL driver rejects a plain date bound to DateTime — see
    # StockTransaction.date).
    credit_note_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    # Nullable: many notes are period/scheme discounts, not tied to one bill.
    linked_purchase_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_invoices.id"), nullable=True
    )
    note_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'GST' | 'COMMERCIAL'
    # DISCOUNT | RATE_DIFFERENCE | QUALITY_CLAIM | SCHEME | GOODS_RETURN (always rejected)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    taxable_value: Mapped[float] = mapped_column(Numeric(15, 2), default=0, server_default=text("0"))
    cgst: Mapped[float] = mapped_column(Numeric(15, 2), default=0, server_default=text("0"))
    sgst: Mapped[float] = mapped_column(Numeric(15, 2), default=0, server_default=text("0"))
    igst: Mapped[float] = mapped_column(Numeric(15, 2), default=0, server_default=text("0"))
    total_amount: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    itc_reversed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    itc_reversal_amount: Mapped[float] = mapped_column(
        Numeric(15, 2), default=0, server_default=text("0")
    )
    # Manually maintained against the GST portal's IMS dashboard (not fetched).
    ims_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", server_default=text("'PENDING'")
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    supplier: Mapped["Supplier"] = relationship()
    linked_purchase_invoice: Mapped["PurchaseInvoice | None"] = relationship()
