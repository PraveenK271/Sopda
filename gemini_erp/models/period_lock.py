from __future__ import annotations

from datetime import date as date_type
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.mixins import AuditMixin


class PeriodLock(Base, AuditMixin):
    """Locks all records dated on or before ``locked_upto_date`` (historical
    import H6). Enforced in the SERVICES so the import path and any future API
    cannot bypass it. Unlock is Administrator-only and recorded on the row —
    locks should be annoying to undo, not impossible.
    """

    __tablename__ = "period_locks"

    id: Mapped[int] = mapped_column(primary_key=True)
    locked_upto_date: Mapped[date_type] = mapped_column(Date, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    locked_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # An unlock deactivates the row and records who/why (kept for the audit trail).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    unlocked_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unlocked_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unlock_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
