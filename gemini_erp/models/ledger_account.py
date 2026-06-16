from __future__ import annotations

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class LedgerAccount(Base, AuditMixin):
    __tablename__ = "ledger_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
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
