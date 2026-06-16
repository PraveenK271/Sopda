from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Date, Integer, String
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

    lines: Mapped[list["JournalEntryLine"]] = relationship(back_populates="entry")
