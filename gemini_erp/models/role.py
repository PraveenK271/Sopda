from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class Role(Base, AuditMixin):
    """A user role with a set of permitted module keys.

    ``permissions`` is a JSON list of module-key strings (see
    ``services/permissions.py``) stored as a JSON string. The model stays dumb —
    the service does the ``json.dumps``/``json.loads`` so the storage format is
    in one place. Explicit ``String(50)``/``Text`` lengths keep it SQL-Server
    clean (Milestone 24 rule: no bare ``String()``).
    """

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    permissions: Mapped[str] = mapped_column(Text, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="role")
