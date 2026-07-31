from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.mixins import AuditMixin


class ImportLog(Base, AuditMixin):
    """One row per historical-import run (validate or import).

    Records what file was processed, its type, how many rows were read and
    records created, the outcome, and any notes (e.g. items that went negative
    during a bulk import — reviewed in the verify/lock milestone H6). Explicit
    String lengths keep it SQL-Server clean (Milestone 24 rule).
    """

    __tablename__ = "import_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'OPENING_STOCK' | 'OPENING_BALANCES' | 'SALES' | 'PURCHASES' | 'RECEIPTS' | 'PAYMENTS'
    import_type: Mapped[str] = mapped_column(String(20), nullable=False)
    run_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    # 'VALIDATED' | 'IMPORTED' | 'FAILED'
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="VALIDATED")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
