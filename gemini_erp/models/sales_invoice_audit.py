from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class SalesInvoiceAudit(Base, AuditMixin):
    """One row per edit of a saved sales invoice (patch v1.1.0, P3).

    before/after snapshots are JSON so the edit history can show exactly what
    changed without the lines having to survive as live rows.
    """

    __tablename__ = "sales_invoice_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("sales_invoices.id"), nullable=False)
    edited_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    edited_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    before_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)

    invoice: Mapped["SalesInvoice"] = relationship()
