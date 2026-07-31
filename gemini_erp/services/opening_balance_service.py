"""Opening balances as of the cut-off date (historical import H2).

The declared opening balances are staged on the ledger `opening_balance` fields
(and `items.opening_stock` for inventory). `post_opening_journal()` then turns
the party/cash balances into ONE balanced double-entry journal (reference_type
'OPENING') and CLEARS those staged fields — so every balance report counts the
opening figure exactly once (via the journal), never twice.

Opening stock is a QUANTITY only (no rupee valuation — see the track's Decision
8); it is the baseline the stock formula starts from, so it never creates a
stock_transaction.

All logic lives here, not in the UI (CLAUDE.md).
"""

import logging
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import false
from sqlalchemy.orm import Session

from models import Customer, Item, JournalEntry, LedgerAccount, Supplier
from services.accounting_service import AccountingService
from services.chart_of_accounts import OPENING_EQUITY

logger = logging.getLogger(__name__)

CUTOFF_DATE = date_type(2026, 3, 31)  # opening balances are AS OF this date


class OpeningBalanceService:
    """Set opening stock / party & cash balances, then post the opening journal."""

    def set_opening_stock(self, session: Session, item_id: int, quantity, created_by: str | None) -> None:
        """Set items.opening_stock (the baseline). Does NOT create a stock movement."""
        item = session.get(Item, item_id)
        if item is None or item.is_deleted:
            raise ValueError(f"Item {item_id} not found")
        qty = Decimal(str(quantity))
        if qty < 0:
            raise ValueError("Opening stock cannot be negative")
        item.opening_stock = qty
        item.modified_by = created_by
        session.commit()
        logger.info("Set opening stock for item %s = %s", item_id, qty)

    def set_party_opening_balance(
        self, session: Session, party_type: str, party_id: int, amount,
        balance_type: str, created_by: str | None,
    ) -> None:
        """Stage a customer/supplier opening balance on its ledger account."""
        party_type = (party_type or "").upper()
        balance_type = (balance_type or "").capitalize()
        if party_type not in ("CUSTOMER", "SUPPLIER"):
            raise ValueError("party_type must be CUSTOMER or SUPPLIER")
        if balance_type not in ("Dr", "Cr"):
            raise ValueError("balance_type must be Dr or Cr")
        amt = Decimal(str(amount))
        if amt <= 0:
            raise ValueError("Opening balance amount must be greater than 0")

        if party_type == "CUSTOMER":
            ledger = session.query(LedgerAccount).filter(LedgerAccount.customer_id == party_id).first()
        else:
            ledger = session.query(LedgerAccount).filter(LedgerAccount.supplier_id == party_id).first()
        if ledger is None:
            raise ValueError(f"{party_type.capitalize()} {party_id} has no ledger account")

        ledger.opening_balance = amt
        ledger.opening_balance_type = balance_type
        ledger.modified_by = created_by
        session.commit()
        logger.info("Set opening balance for %s %s = %s %s", party_type, party_id, amt, balance_type)

    def set_cash_bank_opening(
        self, session: Session, ledger_account_id: int, amount, created_by: str | None
    ) -> None:
        """Stage a cash/bank opening balance (always a Dr asset balance)."""
        ledger = session.get(LedgerAccount, ledger_account_id)
        if ledger is None or ledger.is_deleted:
            raise ValueError(f"Ledger account {ledger_account_id} not found")
        amt = Decimal(str(amount))
        if amt < 0:
            raise ValueError("Cash/bank opening balance cannot be negative")
        ledger.opening_balance = amt
        ledger.opening_balance_type = "Dr"
        ledger.modified_by = created_by
        session.commit()
        logger.info("Set cash/bank opening balance for ledger %s = %s", ledger_account_id, amt)

    def post_opening_journal(
        self, session: Session, as_of_date: date_type, created_by: str | None
    ) -> JournalEntry:
        """Post the one-time opening journal from the staged balances, then clear
        the staged fields so no balance is counted twice.

        Refuses to run if an OPENING journal already exists.
        """
        existing = (
            session.query(JournalEntry)
            .filter(JournalEntry.reference_type == "OPENING", JournalEntry.is_deleted == false())
            .first()
        )
        if existing is not None:
            raise ValueError(
                f"An opening journal already exists (entry id={existing.id}). "
                "Delete or reverse it before posting opening balances again."
            )

        # All staged party/cash balances (exclude the equity account itself).
        equity = AccountingService.get_account_by_code(session, OPENING_EQUITY)
        staged = (
            session.query(LedgerAccount)
            .filter(
                LedgerAccount.opening_balance != 0,
                LedgerAccount.is_deleted == false(),
                LedgerAccount.id != equity.id,
            )
            .all()
        )
        if not staged:
            raise ValueError("No opening balances have been entered.")

        lines = []
        total_dr = Decimal("0")
        total_cr = Decimal("0")
        for acc in staged:
            amt = Decimal(str(acc.opening_balance))
            if acc.opening_balance_type == "Cr":
                lines.append({"account_id": acc.id, "debit": Decimal("0"), "credit": amt})
                total_cr += amt
            else:
                lines.append({"account_id": acc.id, "debit": amt, "credit": Decimal("0")})
                total_dr += amt

        # Opening Balance Equity is the balancing figure.
        diff = total_dr - total_cr
        if diff > 0:
            lines.append({"account_id": equity.id, "debit": Decimal("0"), "credit": diff})
        elif diff < 0:
            lines.append({"account_id": equity.id, "debit": -diff, "credit": Decimal("0")})

        try:
            entry = AccountingService.post_journal_entry(
                session,
                date=as_of_date,
                reference_type="OPENING",
                reference_id=None,
                lines=lines,
                narration=f"Opening balances as of {as_of_date.strftime('%d-%m-%Y')}",
                created_by=created_by,
            )
            # Clear the staged fields — the journal now carries these balances, so
            # reports (which add opening_balance + journal lines) count them once.
            for acc in staged:
                acc.opening_balance = 0
                acc.opening_balance_type = "Dr"
                acc.modified_by = created_by
            session.commit()
            logger.info("Posted opening journal id=%s with %d line(s)", entry.id, len(lines))
            return entry
        except Exception:
            session.rollback()
            logger.exception("Failed to post opening journal")
            raise
