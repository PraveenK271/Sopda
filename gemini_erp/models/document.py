from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class Document(Base, AuditMixin):
    """A stored uploaded file (e.g. a scanned supplier bill) and its OCR status.

    The physical file is copied into the project's ``documents/`` folder; this
    row records where it lives, what it is, the OCR result text/confidence, and
    (once saved) which purchase invoice it produced. OCR is triggered
    separately from upload, so a freshly-saved document starts as ``PENDING``.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    upload_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    document_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PURCHASE_BILL"
    )
    linked_purchase_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_invoices.id"), nullable=True
    )
    # 'PENDING' (uploaded, not scanned) | 'DONE' (OCR ran) | 'FAILED'
    ocr_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="PENDING"
    )
    ocr_raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    linked_purchase_invoice: Mapped["PurchaseInvoice | None"] = relationship()
