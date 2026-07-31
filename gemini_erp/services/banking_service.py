"""Banking: bank accounts, receipts (money in), payments (money out).

Each receipt/payment is written together with its journal entry in a SINGLE
transaction (the "all or nothing" rule), so the books and the cash/bank
position can never drift apart.

Sign / posting conventions:
  Receipt  -> Dr Cash/Bank   Cr Customer ledger   (reference_type='RECEIPT')
  Payment  -> Dr Supplier ledger   Cr Cash/Bank    (reference_type='PAYMENT')
"""

import logging
from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import false, true
from database import get_session
from models import BankAccount, BankStatementLine, LedgerAccount, Payment, Receipt
from services.accounting_service import AccountingService
from services.chart_of_accounts import CASH
from services.period_lock_service import PeriodLockService

logger = logging.getLogger(__name__)


class BankingService:
    """Bank accounts plus receipt/payment recording."""

    # ----- Bank accounts -------------------------------------------------

    def add_bank_account(
        self,
        name: str,
        bank_name: str | None = None,
        account_no: str | None = None,
        ifsc: str | None = None,
        opening_balance: float = 0.0,
        created_by: str | None = None,
    ) -> BankAccount:
        """Create a bank account plus its linked ledger account, one transaction."""
        session = get_session()
        try:
            bank = BankAccount(
                name=name,
                bank_name=bank_name,
                account_no=account_no,
                ifsc=ifsc,
                opening_balance=Decimal(str(opening_balance)),
                created_by=created_by,
            )
            session.add(bank)
            session.flush()  # get bank.id for the FK below

            ledger_account = LedgerAccount(
                name=name,
                account_type="ASSET",
                account_group="Bank Accounts",
                bank_account_id=bank.id,
                opening_balance=Decimal(str(opening_balance)),
                opening_balance_type="Dr",
                created_by=created_by,
            )
            session.add(ledger_account)

            session.commit()
            session.refresh(bank)
            logger.info("Added bank account %s with linked ledger account", bank.name)
            return bank
        except Exception:
            session.rollback()
            logger.exception("Failed to add bank account %s", name)
            raise
        finally:
            session.close()

    def list_bank_accounts(self) -> list[dict]:
        session = get_session()
        try:
            banks = (
                session.query(BankAccount)
                .filter(BankAccount.is_deleted == false())
                .order_by(BankAccount.name)
                .all()
            )
            return [
                {
                    "id": b.id,
                    "name": b.name,
                    "bank_name": b.bank_name,
                    "account_no": b.account_no,
                    "ifsc": b.ifsc,
                    "opening_balance": float(b.opening_balance),
                }
                for b in banks
            ]
        except Exception:
            logger.exception("Failed to list bank accounts")
            raise
        finally:
            session.close()

    # ----- Internal helpers ---------------------------------------------

    @staticmethod
    def _cash_or_bank_account_id(session, payment_mode: str, bank_account_id: int | None) -> int:
        """Resolve the asset ledger account to post against for CASH or BANK."""
        if payment_mode == "CASH":
            return AccountingService.get_account_by_code(session, CASH).id
        if payment_mode == "BANK":
            if bank_account_id is None:
                raise ValueError("bank_account_id is required when payment_mode is 'BANK'")
            ledger = (
                session.query(LedgerAccount)
                .filter(
                    LedgerAccount.bank_account_id == bank_account_id,
                    LedgerAccount.is_deleted == false(),
                )
                .first()
            )
            if ledger is None:
                raise ValueError(f"Bank account {bank_account_id} has no linked ledger account")
            return ledger.id
        raise ValueError(f"Invalid payment_mode '{payment_mode}' (expected 'CASH' or 'BANK')")

    @staticmethod
    def _party_ledger_account(session, *, customer_id=None, supplier_id=None) -> LedgerAccount:
        column = LedgerAccount.customer_id if customer_id is not None else LedgerAccount.supplier_id
        party_id = customer_id if customer_id is not None else supplier_id
        ledger = (
            session.query(LedgerAccount)
            .filter(column == party_id, LedgerAccount.is_deleted == false())
            .first()
        )
        if ledger is None:
            party = "Customer" if customer_id is not None else "Supplier"
            raise ValueError(f"{party} {party_id} has no linked ledger account")
        return ledger

    # ----- Receipts ------------------------------------------------------

    def record_receipt(
        self,
        date: date_type,
        customer_id: int,
        amount: float,
        payment_mode: str,
        bank_account_id: int | None = None,
        reference_no: str | None = None,
        notes: str | None = None,
        created_by: str | None = None,
    ) -> Receipt:
        """Record money received from a customer: Dr Cash/Bank, Cr Customer."""
        amount_dec = Decimal(str(amount))
        if amount_dec <= 0:
            raise ValueError("Receipt amount must be positive")
        PeriodLockService().check_not_locked(date)

        session = get_session()
        try:
            asset_account_id = self._cash_or_bank_account_id(session, payment_mode, bank_account_id)
            cust_ledger = self._party_ledger_account(session, customer_id=customer_id)

            receipt = Receipt(
                date=date,
                customer_id=customer_id,
                payment_mode=payment_mode,
                bank_account_id=bank_account_id if payment_mode == "BANK" else None,
                amount=amount_dec,
                reference_no=reference_no,
                notes=notes,
                created_by=created_by,
            )
            session.add(receipt)
            session.flush()  # get receipt.id for the journal reference

            jnl_lines = [
                {"account_id": asset_account_id, "debit": amount_dec, "credit": Decimal("0")},
                {"account_id": cust_ledger.id, "debit": Decimal("0"), "credit": amount_dec},
            ]
            AccountingService.post_journal_entry(
                session,
                date=date,
                reference_type="RECEIPT",
                reference_id=receipt.id,
                lines=jnl_lines,
                narration=f"Receipt from {cust_ledger.name}",
                created_by=created_by,
            )

            session.commit()
            session.refresh(receipt)
            logger.info("Recorded receipt id=%s amount=%s mode=%s", receipt.id, amount_dec, payment_mode)
            return receipt
        except Exception:
            session.rollback()
            logger.exception("Failed to record receipt for customer %s", customer_id)
            raise
        finally:
            session.close()

    def list_receipts(self) -> list[dict]:
        session = get_session()
        try:
            receipts = (
                session.query(Receipt)
                .filter(Receipt.is_deleted == false())
                .order_by(Receipt.date.desc(), Receipt.id.desc())
                .all()
            )
            return [
                {
                    "id": r.id,
                    "date": r.date,
                    "customer_id": r.customer_id,
                    "customer_name": r.customer.name if r.customer else "",
                    "payment_mode": r.payment_mode,
                    "bank_account_id": r.bank_account_id,
                    "bank_account_name": r.bank_account.name if r.bank_account else "",
                    "amount": float(r.amount),
                    "reference_no": r.reference_no,
                    "notes": r.notes,
                }
                for r in receipts
            ]
        except Exception:
            logger.exception("Failed to list receipts")
            raise
        finally:
            session.close()

    # ----- Payments ------------------------------------------------------

    def record_payment(
        self,
        date: date_type,
        supplier_id: int,
        amount: float,
        payment_mode: str,
        bank_account_id: int | None = None,
        reference_no: str | None = None,
        notes: str | None = None,
        created_by: str | None = None,
    ) -> Payment:
        """Record money paid to a supplier: Dr Supplier, Cr Cash/Bank."""
        amount_dec = Decimal(str(amount))
        if amount_dec <= 0:
            raise ValueError("Payment amount must be positive")
        PeriodLockService().check_not_locked(date)

        session = get_session()
        try:
            asset_account_id = self._cash_or_bank_account_id(session, payment_mode, bank_account_id)
            supp_ledger = self._party_ledger_account(session, supplier_id=supplier_id)

            payment = Payment(
                date=date,
                supplier_id=supplier_id,
                payment_mode=payment_mode,
                bank_account_id=bank_account_id if payment_mode == "BANK" else None,
                amount=amount_dec,
                reference_no=reference_no,
                notes=notes,
                created_by=created_by,
            )
            session.add(payment)
            session.flush()

            jnl_lines = [
                {"account_id": supp_ledger.id, "debit": amount_dec, "credit": Decimal("0")},
                {"account_id": asset_account_id, "debit": Decimal("0"), "credit": amount_dec},
            ]
            AccountingService.post_journal_entry(
                session,
                date=date,
                reference_type="PAYMENT",
                reference_id=payment.id,
                lines=jnl_lines,
                narration=f"Payment to {supp_ledger.name}",
                created_by=created_by,
            )

            session.commit()
            session.refresh(payment)
            logger.info("Recorded payment id=%s amount=%s mode=%s", payment.id, amount_dec, payment_mode)
            return payment
        except Exception:
            session.rollback()
            logger.exception("Failed to record payment for supplier %s", supplier_id)
            raise
        finally:
            session.close()

    def list_payments(self) -> list[dict]:
        session = get_session()
        try:
            payments = (
                session.query(Payment)
                .filter(Payment.is_deleted == false())
                .order_by(Payment.date.desc(), Payment.id.desc())
                .all()
            )
            return [
                {
                    "id": p.id,
                    "date": p.date,
                    "supplier_id": p.supplier_id,
                    "supplier_name": p.supplier.name if p.supplier else "",
                    "payment_mode": p.payment_mode,
                    "bank_account_id": p.bank_account_id,
                    "bank_account_name": p.bank_account.name if p.bank_account else "",
                    "amount": float(p.amount),
                    "reference_no": p.reference_no,
                    "notes": p.notes,
                }
                for p in payments
            ]
        except Exception:
            logger.exception("Failed to list payments")
            raise
        finally:
            session.close()

    # ----- Bank reconciliation (Milestone 17) ----------------------------

    def add_statement_line(
        self,
        bank_account_id: int,
        date: date_type,
        description: str | None,
        amount: float,
        created_by: str | None = None,
    ) -> BankStatementLine:
        """Manually add one bank-statement row (no file import — Decision 4).

        `amount` is signed: positive = deposit, negative = withdrawal.
        """
        amount_dec = Decimal(str(amount))
        if amount_dec == 0:
            raise ValueError("Statement line amount cannot be zero")

        session = get_session()
        try:
            line = BankStatementLine(
                bank_account_id=bank_account_id,
                date=date,
                description=description,
                amount=amount_dec,
                is_matched=False,
                created_by=created_by,
            )
            session.add(line)
            session.commit()
            session.refresh(line)
            logger.info("Added statement line id=%s amount=%s", line.id, amount_dec)
            return line
        except Exception:
            session.rollback()
            logger.exception("Failed to add statement line for bank account %s", bank_account_id)
            raise
        finally:
            session.close()

    def list_unmatched_statement_lines(self, bank_account_id: int) -> list[dict]:
        """Statement lines for this bank account that have not been matched yet."""
        session = get_session()
        try:
            lines = (
                session.query(BankStatementLine)
                .filter(
                    BankStatementLine.bank_account_id == bank_account_id,
                    BankStatementLine.is_matched == false(),
                    BankStatementLine.is_deleted == false(),
                )
                .order_by(BankStatementLine.date, BankStatementLine.id)
                .all()
            )
            return [self._statement_line_dict(line) for line in lines]
        except Exception:
            logger.exception("Failed to list unmatched statement lines for %s", bank_account_id)
            raise
        finally:
            session.close()

    def list_statement_lines(self, bank_account_id: int) -> list[dict]:
        """All statement lines for this bank account (matched and unmatched)."""
        session = get_session()
        try:
            lines = (
                session.query(BankStatementLine)
                .filter(
                    BankStatementLine.bank_account_id == bank_account_id,
                    BankStatementLine.is_deleted == false(),
                )
                .order_by(BankStatementLine.date, BankStatementLine.id)
                .all()
            )
            return [self._statement_line_dict(line) for line in lines]
        except Exception:
            logger.exception("Failed to list statement lines for %s", bank_account_id)
            raise
        finally:
            session.close()

    @staticmethod
    def _statement_line_dict(line: BankStatementLine) -> dict:
        return {
            "id": line.id,
            "bank_account_id": line.bank_account_id,
            "date": line.date,
            "description": line.description,
            "amount": float(line.amount),
            "is_matched": line.is_matched,
            "matched_receipt_id": line.matched_receipt_id,
            "matched_payment_id": line.matched_payment_id,
        }

    def list_unmatched_receipts(self, bank_account_id: int) -> list[dict]:
        """BANK-mode receipts for this account not yet tied to a statement line."""
        return self._unmatched_money_moves(
            bank_account_id, Receipt, BankStatementLine.matched_receipt_id
        )

    def list_unmatched_payments(self, bank_account_id: int) -> list[dict]:
        """BANK-mode payments for this account not yet tied to a statement line."""
        return self._unmatched_money_moves(
            bank_account_id, Payment, BankStatementLine.matched_payment_id
        )

    def _unmatched_money_moves(self, bank_account_id, move_cls, matched_id_column) -> list[dict]:
        session = get_session()
        try:
            already_matched = (
                session.query(matched_id_column)
                .filter(
                    matched_id_column.isnot(None),
                    BankStatementLine.is_deleted == false(),
                )
            )
            moves = (
                session.query(move_cls)
                .filter(
                    move_cls.payment_mode == "BANK",
                    move_cls.bank_account_id == bank_account_id,
                    move_cls.is_deleted == false(),
                    move_cls.id.notin_(already_matched),
                )
                .order_by(move_cls.date, move_cls.id)
                .all()
            )
            party_attr = "customer" if move_cls is Receipt else "supplier"
            return [
                {
                    "id": m.id,
                    "date": m.date,
                    "party_name": getattr(m, party_attr).name if getattr(m, party_attr) else "",
                    "amount": float(m.amount),
                    "reference_no": m.reference_no,
                }
                for m in moves
            ]
        except Exception:
            logger.exception("Failed to list unmatched %s for %s", move_cls.__name__, bank_account_id)
            raise
        finally:
            session.close()

    def match_statement_line(
        self, line_id: int, receipt_id: int | None = None, payment_id: int | None = None
    ) -> BankStatementLine:
        """Tie a statement line to exactly one recorded receipt or payment.

        A deposit (positive line) matches a Receipt; a withdrawal (negative
        line) matches a Payment. Exactly one of receipt_id / payment_id must
        be given, the sign must agree, and the amounts must equal.
        """
        if (receipt_id is None) == (payment_id is None):
            raise ValueError("Provide exactly one of receipt_id or payment_id")

        session = get_session()
        try:
            line = session.get(BankStatementLine, line_id)
            if line is None or line.is_deleted:
                raise ValueError(f"Statement line {line_id} not found")
            if line.is_matched:
                raise ValueError(f"Statement line {line_id} is already matched")

            line_amount = Decimal(str(line.amount))
            if receipt_id is not None:
                if line_amount <= 0:
                    raise ValueError("A receipt can only match a deposit (positive amount)")
                move = session.get(Receipt, receipt_id)
                kind = "Receipt"
            else:
                if line_amount >= 0:
                    raise ValueError("A payment can only match a withdrawal (negative amount)")
                move = session.get(Payment, payment_id)
                kind = "Payment"

            move_id = receipt_id if receipt_id is not None else payment_id
            if move is None or move.is_deleted:
                raise ValueError(f"{kind} {move_id} not found")
            if move.bank_account_id != line.bank_account_id:
                raise ValueError(f"{kind} {move_id} is for a different bank account")
            if abs(Decimal(str(move.amount))) != abs(line_amount):
                raise ValueError(
                    f"Amount mismatch: statement line {abs(line_amount)} != {kind.lower()} {move.amount}"
                )

            line.is_matched = True
            line.matched_receipt_id = receipt_id
            line.matched_payment_id = payment_id
            session.commit()
            session.refresh(line)
            logger.info("Matched statement line id=%s to %s id=%s", line_id, kind, move_id)
            return line
        except Exception:
            session.rollback()
            logger.exception("Failed to match statement line %s", line_id)
            raise
        finally:
            session.close()
