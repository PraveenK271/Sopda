"""Accounting engine: ledger accounts and journal entries.

Methods here take a `session` argument and operate on it directly so they
can run inside the same transaction as the sales/purchase invoice they are
posting for (see Milestone 11).
"""

import logging
from datetime import date as date_type
from decimal import Decimal

from database import get_session
from models import Customer, JournalEntry, JournalEntryLine, LedgerAccount, Supplier

logger = logging.getLogger(__name__)


class AccountingService:
    """Chart of accounts lookups and journal posting."""

    @staticmethod
    def get_account_by_code(session, code: str) -> LedgerAccount:
        account = (
            session.query(LedgerAccount)
            .filter(LedgerAccount.code == code, LedgerAccount.is_deleted.is_(False))
            .first()
        )
        if account is None:
            raise ValueError(f"System ledger account with code '{code}' not found")
        return account

    @staticmethod
    def post_journal_entry(
        session,
        date: date_type,
        reference_type: str,
        reference_id: int | None,
        lines: list[dict],
        narration: str | None = None,
        created_by: str | None = None,
    ) -> JournalEntry:
        """Create a balanced journal entry in the passed-in session.

        lines: list of {"account_id": int, "debit": Decimal, "credit": Decimal}.
        Does NOT commit — the caller's transaction wraps this call.
        """
        total_debit = sum(Decimal(str(l["debit"])) for l in lines)
        total_credit = sum(Decimal(str(l["credit"])) for l in lines)
        if total_debit != total_credit:
            raise ValueError(
                f"Journal entry does not balance: debit {total_debit} != credit {total_credit}"
            )

        entry = JournalEntry(
            date=date,
            reference_type=reference_type,
            reference_id=reference_id,
            narration=narration,
            created_by=created_by,
        )
        session.add(entry)
        session.flush()  # get entry.id before adding lines

        for line in lines:
            session.add(
                JournalEntryLine(
                    entry_id=entry.id,
                    account_id=line["account_id"],
                    debit=Decimal(str(line["debit"])),
                    credit=Decimal(str(line["credit"])),
                    created_by=created_by,
                )
            )

        logger.info(
            "Posted journal entry id=%s %s/%s: %d lines",
            entry.id, reference_type, reference_id, len(lines),
        )
        return entry

    @staticmethod
    def list_accounts() -> list[dict]:
        """All non-deleted ledger accounts, ordered for the account picker."""
        session = get_session()
        try:
            accounts = (
                session.query(LedgerAccount)
                .filter(LedgerAccount.is_deleted.is_(False))
                .order_by(LedgerAccount.account_type, LedgerAccount.name)
                .all()
            )
            return [
                {
                    "id": a.id,
                    "name": a.name,
                    "code": a.code,
                    "account_type": a.account_type,
                    "account_group": a.account_group,
                }
                for a in accounts
            ]
        except Exception:
            logger.exception("Failed to list accounts")
            raise
        finally:
            session.close()

    @staticmethod
    def get_day_book(date_from: date_type, date_to: date_type) -> list[dict]:
        """Every journal entry between date_from and date_to with its lines, newest first."""
        session = get_session()
        try:
            entries = (
                session.query(JournalEntry)
                .filter(
                    JournalEntry.date >= date_from,
                    JournalEntry.date <= date_to,
                    JournalEntry.is_deleted.is_(False),
                )
                .order_by(JournalEntry.date.desc(), JournalEntry.id.desc())
                .all()
            )
            result = []
            for entry in entries:
                lines = [l for l in entry.lines if not l.is_deleted]
                result.append({
                    "id": entry.id,
                    "date": entry.date,
                    "reference_type": entry.reference_type,
                    "reference_id": entry.reference_id,
                    "narration": entry.narration or "",
                    "lines": [
                        {
                            "account_name": l.account.name,
                            "account_group": l.account.account_group,
                            "debit": float(l.debit),
                            "credit": float(l.credit),
                        }
                        for l in lines
                    ],
                })
            return result
        except Exception:
            logger.exception("Failed to load day book")
            raise
        finally:
            session.close()

    @staticmethod
    def get_ledger(
        account_id: int,
        date_from: date_type | None = None,
        date_to: date_type | None = None,
    ) -> dict:
        """Ledger for one account: opening balance, dated entries with running balance,
        closing balance.

        Running balance convention: positive = Dr, negative = Cr.
        """
        session = get_session()
        try:
            account = session.get(LedgerAccount, account_id)
            if account is None:
                raise ValueError(f"Ledger account {account_id} not found")

            query = (
                session.query(JournalEntryLine, JournalEntry)
                .join(JournalEntry, JournalEntryLine.entry_id == JournalEntry.id)
                .filter(
                    JournalEntryLine.account_id == account_id,
                    JournalEntryLine.is_deleted.is_(False),
                    JournalEntry.is_deleted.is_(False),
                )
            )
            if date_from:
                query = query.filter(JournalEntry.date >= date_from)
            if date_to:
                query = query.filter(JournalEntry.date <= date_to)
            rows = query.order_by(JournalEntry.date, JournalEntry.id).all()

            opening = float(account.opening_balance)
            if account.opening_balance_type == "Cr":
                opening = -opening

            running = opening
            entries = []
            for line, entry in rows:
                dr = float(line.debit)
                cr = float(line.credit)
                running += dr - cr
                entries.append({
                    "date": entry.date,
                    "narration": entry.narration or "",
                    "reference_type": entry.reference_type,
                    "debit": dr,
                    "credit": cr,
                    "balance": abs(running),
                    "balance_type": "Dr" if running >= 0 else "Cr",
                })

            return {
                "account_name": account.name,
                "account_group": account.account_group,
                "opening_balance": abs(opening),
                "opening_balance_type": "Dr" if opening >= 0 else "Cr",
                "entries": entries,
                "closing_balance": abs(running),
                "closing_balance_type": "Dr" if running >= 0 else "Cr",
            }
        except Exception:
            logger.exception("Failed to load ledger for account %s", account_id)
            raise
        finally:
            session.close()

    @staticmethod
    def get_trial_balance(as_of_date: date_type | None = None) -> list[dict]:
        """One row per account with a non-zero net balance as of as_of_date (or all time).

        Each row: {"account_name", "account_group", "account_type", "debit", "credit"}
        — the net balance is shown on its natural side (Dr balance in debit column,
        Cr balance in credit column). Total debit == total credit is the fundamental
        double-entry check.
        """
        from sqlalchemy import func as sqlfunc

        session = get_session()
        try:
            # Sum posted debits and credits per account, filtered by date via journal_entries.
            line_query = (
                session.query(
                    JournalEntryLine.account_id,
                    sqlfunc.coalesce(sqlfunc.sum(JournalEntryLine.debit), 0).label("total_dr"),
                    sqlfunc.coalesce(sqlfunc.sum(JournalEntryLine.credit), 0).label("total_cr"),
                )
                .join(JournalEntry, JournalEntryLine.entry_id == JournalEntry.id)
                .filter(
                    JournalEntryLine.is_deleted.is_(False),
                    JournalEntry.is_deleted.is_(False),
                )
            )
            if as_of_date:
                line_query = line_query.filter(JournalEntry.date <= as_of_date)
            line_query = line_query.group_by(JournalEntryLine.account_id)
            line_totals = {
                row.account_id: (float(row.total_dr), float(row.total_cr))
                for row in line_query.all()
            }

            accounts = (
                session.query(LedgerAccount)
                .filter(LedgerAccount.is_deleted.is_(False))
                .all()
            )

            result = []
            for account in accounts:
                total_dr, total_cr = line_totals.get(account.id, (0.0, 0.0))
                opening = float(account.opening_balance)
                if account.opening_balance_type == "Cr":
                    opening = -opening

                net = opening + total_dr - total_cr
                if abs(net) < 0.001:
                    continue

                result.append({
                    "account_name": account.name,
                    "account_group": account.account_group,
                    "account_type": account.account_type,
                    "debit": round(net, 2) if net > 0 else 0.0,
                    "credit": round(-net, 2) if net < 0 else 0.0,
                })

            result.sort(key=lambda r: (r["account_type"], r["account_name"]))
            return result
        except Exception:
            logger.exception("Failed to compute trial balance")
            raise
        finally:
            session.close()

    @staticmethod
    def _line_totals_by_account(session, date_from=None, date_to=None) -> dict:
        """Helper: returns {account_id: (total_dr, total_cr)} for posted journal lines."""
        from sqlalchemy import func as sqlfunc
        q = (
            session.query(
                JournalEntryLine.account_id,
                sqlfunc.coalesce(sqlfunc.sum(JournalEntryLine.debit), 0).label("dr"),
                sqlfunc.coalesce(sqlfunc.sum(JournalEntryLine.credit), 0).label("cr"),
            )
            .join(JournalEntry, JournalEntryLine.entry_id == JournalEntry.id)
            .filter(
                JournalEntryLine.is_deleted.is_(False),
                JournalEntry.is_deleted.is_(False),
            )
        )
        if date_from:
            q = q.filter(JournalEntry.date >= date_from)
        if date_to:
            q = q.filter(JournalEntry.date <= date_to)
        q = q.group_by(JournalEntryLine.account_id)
        return {row.account_id: (float(row.dr), float(row.cr)) for row in q.all()}

    @staticmethod
    def get_profit_and_loss(date_from: date_type, date_to: date_type) -> dict:
        """Income and expense accounts for the period, plus net profit.

        KNOWN LIMITATION (see CHECKLIST_PHASE2_PART2.md Decision 3): the Purchase
        Account balance is treated as a period expense regardless of unsold closing
        stock. This is a timing difference — the system has no item cost/valuation yet.
        """
        session = get_session()
        try:
            totals = AccountingService._line_totals_by_account(session, date_from, date_to)
            accounts = (
                session.query(LedgerAccount)
                .filter(
                    LedgerAccount.is_deleted.is_(False),
                    LedgerAccount.account_type.in_(["INCOME", "EXPENSE"]),
                )
                .all()
            )

            income = []
            expenses = []
            for acct in accounts:
                dr, cr = totals.get(acct.id, (0.0, 0.0))
                if acct.account_type == "INCOME":
                    amount = cr - dr  # income grows on the credit side
                    if abs(amount) > 0.001:
                        income.append({"account_name": acct.name, "account_group": acct.account_group, "amount": round(amount, 2)})
                else:
                    amount = dr - cr  # expense grows on the debit side
                    if abs(amount) > 0.001:
                        expenses.append({"account_name": acct.name, "account_group": acct.account_group, "amount": round(amount, 2)})

            net_profit = round(sum(r["amount"] for r in income) - sum(r["amount"] for r in expenses), 2)
            return {
                "income": sorted(income, key=lambda r: r["account_name"]),
                "expenses": sorted(expenses, key=lambda r: r["account_name"]),
                "net_profit": net_profit,
            }
        except Exception:
            logger.exception("Failed to compute P&L")
            raise
        finally:
            session.close()

    @staticmethod
    def get_balance_sheet(as_of_date: date_type | None = None) -> dict:
        """Assets, liabilities, and net profit to date.

        By double-entry construction: sum(assets) == sum(liabilities) + net_profit_to_date.
        The net_profit_to_date line is shown under liabilities for readability.
        """
        session = get_session()
        try:
            totals = AccountingService._line_totals_by_account(session, date_to=as_of_date)
            accounts = (
                session.query(LedgerAccount)
                .filter(LedgerAccount.is_deleted.is_(False))
                .all()
            )

            assets = []
            liabilities = []
            net_income = 0.0
            net_expenses = 0.0

            for acct in accounts:
                dr, cr = totals.get(acct.id, (0.0, 0.0))
                opening = float(acct.opening_balance)
                if acct.opening_balance_type == "Cr":
                    opening = -opening
                net = opening + dr - cr  # positive = Dr

                if acct.account_type == "ASSET":
                    if abs(net) > 0.001:
                        assets.append({"account_name": acct.name, "account_group": acct.account_group, "amount": round(net, 2)})
                elif acct.account_type in ("LIABILITY", "EQUITY"):
                    if abs(net) > 0.001:
                        liabilities.append({"account_name": acct.name, "account_group": acct.account_group, "amount": round(-net, 2)})
                elif acct.account_type == "INCOME":
                    net_income += cr - dr
                elif acct.account_type == "EXPENSE":
                    net_expenses += dr - cr

            net_profit_to_date = round(net_income - net_expenses, 2)
            return {
                "assets": sorted(assets, key=lambda r: r["account_name"]),
                "liabilities": sorted(liabilities, key=lambda r: r["account_name"]),
                "net_profit_to_date": net_profit_to_date,
            }
        except Exception:
            logger.exception("Failed to compute balance sheet")
            raise
        finally:
            session.close()

    @staticmethod
    def get_outstanding_customers() -> list[dict]:
        """Customers with a net Dr balance (they owe us money).

        Returns list of {"customer_id", "name", "gstin", "outstanding"}, sorted by name.
        """
        session = get_session()
        try:
            totals = AccountingService._line_totals_by_account(session)
            rows = (
                session.query(LedgerAccount, Customer)
                .join(Customer, LedgerAccount.customer_id == Customer.id)
                .filter(
                    LedgerAccount.customer_id.isnot(None),
                    LedgerAccount.is_deleted.is_(False),
                    Customer.is_deleted.is_(False),
                )
                .all()
            )
            result = []
            for account, customer in rows:
                dr, cr = totals.get(account.id, (0.0, 0.0))
                opening = float(account.opening_balance)
                if account.opening_balance_type == "Cr":
                    opening = -opening
                net = opening + dr - cr
                if net > 0.001:
                    result.append({
                        "customer_id": customer.id,
                        "name": customer.name,
                        "gstin": customer.gstin,
                        "outstanding": round(net, 2),
                    })
            result.sort(key=lambda r: r["name"])
            return result
        except Exception:
            logger.exception("Failed to compute outstanding customers")
            raise
        finally:
            session.close()

    @staticmethod
    def get_outstanding_suppliers() -> list[dict]:
        """Suppliers with a net Cr balance (we owe them money).

        Returns list of {"supplier_id", "name", "gstin", "outstanding"}, sorted by name.
        """
        session = get_session()
        try:
            totals = AccountingService._line_totals_by_account(session)
            rows = (
                session.query(LedgerAccount, Supplier)
                .join(Supplier, LedgerAccount.supplier_id == Supplier.id)
                .filter(
                    LedgerAccount.supplier_id.isnot(None),
                    LedgerAccount.is_deleted.is_(False),
                    Supplier.is_deleted.is_(False),
                )
                .all()
            )
            result = []
            for account, supplier in rows:
                dr, cr = totals.get(account.id, (0.0, 0.0))
                opening = float(account.opening_balance)
                if account.opening_balance_type == "Cr":
                    opening = -opening
                net = opening + dr - cr
                if net < -0.001:  # Cr balance = we owe the supplier
                    result.append({
                        "supplier_id": supplier.id,
                        "name": supplier.name,
                        "gstin": supplier.gstin,
                        "outstanding": round(-net, 2),
                    })
            result.sort(key=lambda r: r["name"])
            return result
        except Exception:
            logger.exception("Failed to compute outstanding suppliers")
            raise
        finally:
            session.close()
