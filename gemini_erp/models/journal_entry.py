from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Boolean, Date, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class JournalEntry(Base, AuditMixin):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    reference_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    narration: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Patch v1.1.0 (migration 002): set once a reversing entry has been posted
    # against this one, so a second invoice edit cannot reverse it again.
    is_reversed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"), nullable=False
    )

    lines: Mapped[list["JournalEntryLine"]] = relationship(back_populates="entry")
