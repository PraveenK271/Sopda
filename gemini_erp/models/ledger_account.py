from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class LedgerAccount(Base, AuditMixin):
    __tablename__ = "ledger_accounts"

    # `code` is unique only among the accounts that HAVE one. Customer/supplier
    # subledgers are created without a code (NULL). A plain UNIQUE constraint is
    # fine on SQLite (many NULLs allowed) but SQL Server permits only ONE NULL in
    # a UNIQUE column, so we use a filtered unique index (WHERE code IS NOT NULL)
    # which enforces "unique among non-null codes" identically on both backends.
    __table_args__ = (
        Index(
            "uq_ledger_accounts_code",
            "code",
            unique=True,
            mssql_where=text("code IS NOT NULL"),
            sqlite_where=text("code IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    account_group: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    bank_account_id: Mapped[int | None] = mapped_column(ForeignKey("bank_accounts.id"), nullable=True)
    opening_balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    opening_balance_type: Mapped[str] = mapped_column(String(2), default="Dr")

    customer: Mapped["Customer | None"] = relationship(back_populates="ledger_account")
    supplier: Mapped["Supplier | None"] = relationship(back_populates="ledger_account")
    bank_account: Mapped["BankAccount | None"] = relationship(back_populates="ledger_account")
