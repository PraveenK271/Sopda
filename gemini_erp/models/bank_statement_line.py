from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.mixins import AuditMixin


class BankStatementLine(Base, AuditMixin):
    """A manually-entered row from a bank statement, for reconciliation.

    `amount` is SIGNED: positive = deposit (money in), negative = withdrawal
    (money out). A line is matched against exactly one recorded Receipt
    (deposit) or Payment (withdrawal). No file import — manual entry only
    (see CHECKLIST_PHASE2_PART2.md Decision 4).
    """

    __tablename__ = "bank_statement_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    bank_account_id: Mapped[int] = mapped_column(
        ForeignKey("bank_accounts.id"), nullable=False
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    is_matched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    matched_receipt_id: Mapped[int | None] = mapped_column(
        ForeignKey("receipts.id"), nullable=True
    )
    matched_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id"), nullable=True
    )

    bank_account: Mapped["BankAccount"] = relationship()
    matched_receipt: Mapped["Receipt | None"] = relationship()
    matched_payment: Mapped["Payment | None"] = relationship()
