from __future__ import annotations

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class BankAccount(Base, AuditMixin):
    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ifsc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    opening_balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    # The chart-of-accounts row that mirrors this bank account (group "Bank Accounts").
    ledger_account: Mapped["LedgerAccount | None"] = relationship(
        back_populates="bank_account", uselist=False
    )
