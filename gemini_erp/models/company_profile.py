from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.mixins import AuditMixin


class CompanyProfile(Base, AuditMixin):
    """Our own (seller) company details — a single-row table.

    Replaces the hardcoded ``reports/company_info.py`` placeholder: invoices and
    reports read these values from the database so a user can edit them on the
    Settings screen without touching code. Only one row is ever used (the
    Settings service reads/creates the single non-deleted row); ``id`` exists
    only as a primary key.
    """

    __tablename__ = "company_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)

    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bank_account_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_ifsc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Terms & conditions printed on the invoice, one per line (newline-separated).
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
