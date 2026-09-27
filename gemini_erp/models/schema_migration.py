from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.mixins import AuditMixin


class SchemaMigration(Base, AuditMixin):
    """One row per applied numbered migration (see migrations/).

    The presence of a version here is the ONLY thing that marks a migration as
    done — MigrationService writes it in the same transaction as the schema
    change, so a failed migration is never recorded.
    """

    __tablename__ = "schema_migrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    applied_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    applied_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
