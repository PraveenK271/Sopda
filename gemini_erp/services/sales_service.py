"""Business logic for sales invoices.

create_invoice() saves the invoice header, its line items, and one OUT
stock_transaction per line, all inside a single database transaction
(see CLAUDE.md - "One transaction = all or nothing").

update_invoice() (patch v1.1.0, P3) edits a saved invoice by REVERSING its
stock movements and journal entries and RE-POSTING the new ones — nothing is
deleted. See its docstring for why this is the design, and do not "optimise"
it into a diff of old vs new lines.

cancel_invoice() (patch v1.2.0, D1) voids a sale the same way — reversing
entries, no re-post — and marks the invoice CANCELLED. It is never a delete:
the number stays used (GST Rule 46(b): the serial stays consecutive, cancelled
invoices are listed in GSTR-1, not erased) and the lines stay readable.
correct_invoice_number() (D2) fixes a mistyped number: a label change only,
no stock or accounting movement.
"""

import json
import logging
import re
from datetime import date as date_type
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, false, func, true
from sqlalchemy.exc import IntegrityError
from database import get_session
from models import (
    Customer,
    Item,
    JournalEntry,
    Receipt,
    SalesInvoice,
    SalesInvoiceAudit,
    SalesInvoiceItem,
    StockTransaction,
)
from services.accounting_service import AccountingService
from services.auth_service import AuthService
from services.gst_service import split_gst
from services.period_lock_service import PeriodLockService
from services.permissions import ROLE_ACCOUNTANT, ROLE_ADMINISTRATOR
from services.settings_service import SettingsService

logger = logging.getLogger(__name__)

# reference_type values for stock_transactions / journal_entries.
REF_SALE = "SALE"
# Both the reversing stock rows and the reversing journal entry of an edit.
REF_SALE_EDIT_REVERSAL = "SALE_EDIT_REVERSAL"
# Both the reversing stock rows and the reversing journal entry of a cancellation.
REF_SALE_CANCELLATION = "SALE_CANCELLATION"

# sales_invoices.status
STATUS_ACTIVE = "ACTIVE"
STATUS_CANCELLED = "CANCELLED"

# sales_invoice_audit.action
ACTION_EDIT = "EDIT"
ACTION_CANCEL = "CANCEL"
ACTION_NUMBER_CORRECTION = "NUMBER_CORRECTION"

# Only these roles may edit a saved invoice (enforced here, not just in the UI).
INVOICE_EDIT_ROLES = (ROLE_ADMINISTRATOR, ROLE_ACCOUNTANT)
# Cancelling and renumbering are stricter: Administrator only.
INVOICE_CANCEL_ROLES = (ROLE_ADMINISTRATOR,)

NO_LINES_MESSAGE = (
    "An invoice must have at least one item. To void the whole sale, cancel the "
    "invoice instead."
)
GST_FILED_MESSAGE = (
    "GSTR-1 for this period has been filed (GST returns are filed up to {upto}). "
    "Issue a credit note instead of {verb}."
)

# GST Rule 46(b): a consecutive serial number of up to 16 characters, made of
# letters, digits, hyphen "-" and slash "/".
INVOICE_NO_MAX_LENGTH = 16
_INVOICE_NO_PATTERN = re.compile(r"^[A-Za-z0-9/-]+$")


def validate_invoice_no(invoice_no) -> str:
    """Return the cleaned invoice number or raise ValueError.

    One rule for every way a number enters the system — a new invoice, a
    number correction, and the historical import — so a correction can never
    produce a number a new invoice would not have been allowed to have.
    """
    cleaned = (invoice_no or "").strip()
    if not cleaned:
        raise ValueError("The invoice number is required.")
    if len(cleaned) > INVOICE_NO_MAX_LENGTH:
        raise ValueError(
            f"Invoice number '{cleaned}' is {len(cleaned)} characters; GST allows at most "
            f"{INVOICE_NO_MAX_LENGTH}."
        )
    if not _INVOICE_NO_PATTERN.match(cleaned):
        raise ValueError(
            f"Invoice number '{cleaned}' may contain only letters, digits, '-' and '/' "
            "(GST Rule 46(b))."
        )
    return cleaned


class InvoiceEditPermissionError(PermissionError):
    """The user's role may not edit saved sales invoices."""


class SalesService:
    """Create sales invoices with automatic stock deduction and GST split."""

    def create_invoice(
        self,
        invoice_no: str,
        invoice_date: date_type,
        customer_id: int,
        lines: list[dict],
        created_by: str | None = None,
    ) -> SalesInvoice:
        """lines: list of {"item_id": int, "quantity": Decimal-like, "rate": Decimal-like}."""
        if not lines:
            raise ValueError("An invoice must have at least one line item")
        invoice_no = validate_invoice_no(invoice_no)
        PeriodLockService().check_not_locked(invoice_date)

        session = get_session()
        try:
            customer = session.get(Customer, customer_id)
            if customer is None:
                raise ValueError(f"Customer {customer_id} not found")

            invoice = SalesInvoice(
                invoice_no=invoice_no,
                date=invoice_date,
                customer_id=customer_id,
                taxable_amount=0,
                cgst=0,
                sgst=0,
                igst=0,
                total=0,
                created_by=created_by,
            )
            session.add(invoice)
            session.flush()  # assign invoice.id within this transaction

            items_sold = self._apply_lines_and_accounting(
                session, invoice, customer, lines, invoice_date,
                narration=f"Sales Invoice {invoice_no}", created_by=created_by,
            )

            session.commit()
            session.refresh(invoice)
            # Non-blocking oversell check on the committed stock. Attached as a
            # transient attribute (not a DB column) for the UI to surface.
            invoice.stock_warnings = self._negative_stock_warnings(session, items_sold)
            for warning in invoice.stock_warnings:
                logger.warning("Oversell on invoice %s: %s", invoice.invoice_no, warning)
            logger.info("Created invoice %s with %d line(s)", invoice.invoice_no, len(lines))
            return invoice
        except IntegrityError:
            # Race-safe manual numbering: the UNIQUE(invoice_no) constraint is the
            # authority. If two clients save the same number, one commit wins and
            # the other lands here — surface a clear message, not a raw DB error.
            session.rollback()
            logger.warning("Duplicate invoice number '%s' rejected", invoice_no)
            raise ValueError(
                f"Invoice number '{invoice_no}' is already used. Please use a different number."
            )
        except Exception:
            session.rollback()
            logger.exception("Failed to create invoice %s", invoice_no)
            raise
        finally:
            session.close()

    def _apply_lines_and_accounting(
        self, session, invoice, customer, lines, invoice_date, narration, created_by,
        require_active_items: bool = False,
    ) -> dict[int, list]:
        """Write `invoice`'s line items + one OUT stock row per line, set its
        header totals, and post the balanced journal entry.

        Shared by create and edit so an edited invoice is priced by exactly the
        same GST rules (state-based CGST+SGST vs IGST) as a new one. Operates on
        the caller's session/transaction; never commits. Returns
        {item_id: [item, quantity sold]} for the oversell warning.

        require_active_items: an edit validates its NEW lines against active
        items (an item soft-deleted from the master cannot be sold again), while
        the reversal of old lines never is.
        """
        total_taxable = total_cgst = total_sgst = total_igst = Decimal("0")
        # Track net quantity sold per item so we can warn (not block) if a
        # line drives stock below zero — the chosen oversell policy is
        # "allow but warn" (multi-user: two clients can both sell the last
        # units; we record both and flag the negative stock).
        items_sold: dict[int, list] = {}

        for line in lines:
            item = session.get(Item, line["item_id"])
            if item is None or (require_active_items and item.is_deleted):
                raise ValueError(f"Item {line['item_id']} not found")

            quantity = Decimal(str(line["quantity"]))
            rate = Decimal(str(line["rate"]))
            amount = (quantity * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            cgst, sgst, igst = split_gst(amount, item.gst_rate, customer.state)
            gst_amount = cgst + sgst + igst

            session.add(
                SalesInvoiceItem(
                    invoice_id=invoice.id,
                    item_id=item.id,
                    quantity=quantity,
                    rate=rate,
                    amount=amount,
                    gst_amount=gst_amount,
                    created_by=created_by,
                )
            )
            session.add(
                StockTransaction(
                    item_id=item.id,
                    type="OUT",
                    quantity=quantity,
                    reference_type=REF_SALE,
                    reference_id=invoice.id,
                    date=invoice_date,
                    created_by=created_by,
                )
            )

            total_taxable += amount
            total_cgst += cgst
            total_sgst += sgst
            total_igst += igst

            entry = items_sold.get(item.id)
            if entry is None:
                items_sold[item.id] = [item, quantity]
            else:
                entry[1] += quantity

        invoice.taxable_amount = total_taxable
        invoice.cgst = total_cgst
        invoice.sgst = total_sgst
        invoice.igst = total_igst
        invoice.total = total_taxable + total_cgst + total_sgst + total_igst

        # --- accounting journal entry ---
        cust_ledger = customer.ledger_account
        if cust_ledger is None:
            raise ValueError(
                f"Customer {customer.id} has no linked ledger account. "
                "Re-add the customer or run create_db.py to seed accounts."
            )
        sales_acct = AccountingService.get_account_by_code(session, "SALES")
        jnl_lines = [
            {"account_id": cust_ledger.id, "debit": invoice.total, "credit": Decimal("0")},
            {"account_id": sales_acct.id, "debit": Decimal("0"), "credit": total_taxable},
        ]
        if total_cgst:
            acct = AccountingService.get_account_by_code(session, "CGST_OUTPUT")
            jnl_lines.append({"account_id": acct.id, "debit": Decimal("0"), "credit": total_cgst})
        if total_sgst:
            acct = AccountingService.get_account_by_code(session, "SGST_OUTPUT")
            jnl_lines.append({"account_id": acct.id, "debit": Decimal("0"), "credit": total_sgst})
        if total_igst:
            acct = AccountingService.get_account_by_code(session, "IGST_OUTPUT")
            jnl_lines.append({"account_id": acct.id, "debit": Decimal("0"), "credit": total_igst})
        AccountingService.post_journal_entry(
            session,
            date=invoice_date,
            reference_type=REF_SALE,
            reference_id=invoice.id,
            lines=jnl_lines,
            narration=narration,
            created_by=created_by,
        )
        return items_sold

    # ----- edit a saved invoice (patch v1.1.0, P3) ------------------------

    @staticmethod
    def user_can_edit_invoices(user) -> bool:
        """Whether a (logged-in) user's role may edit saved invoices. For the UI
        to decide whether to show the Edit button; update_invoice() enforces
        the same rule itself."""
        return bool(
            user is not None and user.role is not None and user.role.name in INVOICE_EDIT_ROLES
        )

    @staticmethod
    def user_can_cancel_invoices(user) -> bool:
        """Whether a user's role may cancel or renumber saved invoices
        (Administrator only). For the UI; the service enforces it again."""
        return bool(
            user is not None and user.role is not None and user.role.name in INVOICE_CANCEL_ROLES
        )

    def preview_invoice_edit(
        self, invoice_id: int, new_data: dict, reason: str, modified_by: str | None
    ) -> list[str]:
        """Run every pre-edit check WITHOUT writing anything.

        Raises for anything that blocks the edit (permission, locked period,
        changed invoice number, no lines, month change, empty reason). Returns
        the list of warnings the user should confirm first (earlier month,
        changed customer, receipts recorded). The UI calls this, shows the
        warnings, then calls update_invoice().
        """
        session = get_session()
        try:
            invoice = self._load_editable_invoice(session, invoice_id)
            return self._check_edit(session, invoice, new_data, reason, modified_by)
        finally:
            session.close()

    def update_invoice(
        self, invoice_id: int, new_data: dict, reason: str, modified_by: str | None
    ) -> SalesInvoice:
        """Edit a saved sales invoice: reverse everything, then re-post.

        new_data: {"customer_id", "date", "lines": [{"item_id", "quantity",
        "rate"}], "invoice_no" (optional — must equal the current number)}.

        Why reverse-then-re-post and never delete: a posted journal is reversed,
        never deleted (auditors expect the trail); get_current_stock() needs no
        change because OUT 10 + reversal IN 10 + new OUT 8 nets to 8; and the
        stock ledger honestly shows the edit. It also handles a REMOVED line for
        free — every active OUT row is reversed and only the new line set is
        re-posted, so there is no "removed line" code path to get wrong.

        All in ONE transaction:
          1-2. load the invoice; run the checks — before any write
          3.   snapshot the invoice as it was
          4.   for EACH OUT stock row of this invoice not yet reversed (per row,
               never grouped by item — one item can be on two lines), write a
               reversing IN dated like the row it reverses, and flag the row
               is_reversed (so a second edit cannot reverse it again)
          5.   same for each journal entry not yet reversed: post the mirror
               entry through AccountingService.post_journal_entry (which refuses
               an unbalanced entry) and flag it is_reversed
          6.   soft-delete the old lines
          7.   write the new lines, OUT rows and journal (same GST rules)
          8.   header totals, edit_count + 1, last_edited_date
          9.   the sales_invoice_audit row with both snapshots
          10.  commit — or roll ALL of it back on any error

        Returns the invoice with transient ``edit_warnings`` (the confirmed
        warnings) and ``stock_warnings`` (oversell after the edit — the same
        "allow but warn" policy as a new sale; availability therefore already
        counts the old quantities coming back, without double-counting them).
        """
        session = get_session()
        try:
            invoice = self._load_editable_invoice(session, invoice_id)
            edit_warnings = self._check_edit(session, invoice, new_data, reason, modified_by)
            new_date = new_data.get("date") or invoice.date
            customer = session.get(Customer, new_data.get("customer_id") or invoice.customer_id)

            before = self._snapshot(invoice)

            # 4-5. reverse every stock row and journal entry not yet reversed.
            self._reverse_postings(
                session, invoice, REF_SALE_EDIT_REVERSAL,
                f"edit of Sales Invoice {invoice.invoice_no}", modified_by,
            )

            # 6. soft-delete the old lines.
            for line in invoice.items:
                if not line.is_deleted:
                    line.is_deleted = True
                    line.modified_by = modified_by

            # 7-8. re-post the new version.
            invoice.date = new_date
            invoice.customer_id = customer.id
            invoice.edit_count = (invoice.edit_count or 0) + 1
            invoice.last_edited_date = datetime.utcnow()
            invoice.modified_by = modified_by
            session.flush()
            items_sold = self._apply_lines_and_accounting(
                session, invoice, customer, new_data["lines"], new_date,
                narration=f"Sales Invoice {invoice.invoice_no} (edit #{invoice.edit_count})",
                created_by=modified_by, require_active_items=True,
            )

            # 9. audit row — reload the lines so the snapshot shows the new set.
            session.flush()
            session.expire(invoice, ["items", "customer"])
            session.add(
                SalesInvoiceAudit(
                    invoice_id=invoice.id,
                    edited_by=modified_by,
                    edited_date=invoice.last_edited_date,
                    reason=reason.strip(),
                    before_snapshot=json.dumps(before),
                    after_snapshot=json.dumps(self._snapshot(invoice)),
                    action=ACTION_EDIT,
                    created_by=modified_by,
                )
            )

            session.commit()
            session.refresh(invoice)
            invoice.edit_warnings = edit_warnings
            invoice.stock_warnings = self._negative_stock_warnings(session, items_sold)
            for warning in invoice.stock_warnings:
                logger.warning("Oversell after editing invoice %s: %s", invoice.invoice_no, warning)
            logger.info(
                "Edited invoice %s (edit #%s) by %s: %s",
                invoice.invoice_no, invoice.edit_count, modified_by, reason.strip(),
            )
            return invoice
        except Exception:
            session.rollback()
            logger.exception("Failed to edit invoice %s", invoice_id)
            raise
        finally:
            session.close()

    @staticmethod
    def _load_editable_invoice(session, invoice_id: int) -> SalesInvoice:
        """The invoice, if it may still be changed. A cancelled invoice is
        read-only: it may not be edited, re-cancelled or renumbered."""
        invoice = session.get(SalesInvoice, invoice_id)
        if invoice is None or invoice.is_deleted:
            raise ValueError(f"Invoice {invoice_id} not found")
        if invoice.status == STATUS_CANCELLED:
            raise ValueError(
                f"Invoice {invoice.invoice_no} is already cancelled. A cancelled invoice "
                "is read-only and cannot be edited, cancelled again or renumbered."
            )
        return invoice

    @staticmethod
    def _reverse_postings(session, invoice, reversal_ref_type: str, reason_text: str, user) -> None:
        """Post reversing entries for every stock row and journal entry of this
        invoice that is still in force, and flag each original is_reversed.

        Shared by edit and cancel. Per STOCK ROW, never grouped by item (one
        item can be on two lines). Only rows with is_reversed False — so a row
        superseded by an earlier edit is never reversed a second time (the
        "second-edit trap"). Reversals are dated like the rows they cancel
        (the invoice date), not today, so the stock ledger and the period P&L
        read correctly. Never commits.
        """
        out_rows = (
            session.query(StockTransaction)
            .filter(
                StockTransaction.reference_type == REF_SALE,
                StockTransaction.reference_id == invoice.id,
                StockTransaction.type == "OUT",
                StockTransaction.is_reversed == false(),
                StockTransaction.is_deleted == false(),
            )
            .order_by(StockTransaction.id)
            .all()
        )
        for row in out_rows:
            # No active-item check: an item soft-deleted from the master since
            # the sale must still get its stock back.
            session.add(
                StockTransaction(
                    item_id=row.item_id,
                    type="IN",
                    quantity=row.quantity,
                    reference_type=reversal_ref_type,
                    reference_id=invoice.id,
                    date=row.date,
                    created_by=user,
                )
            )
            row.is_reversed = True
            row.modified_by = user

        entries = (
            session.query(JournalEntry)
            .filter(
                JournalEntry.reference_type == REF_SALE,
                JournalEntry.reference_id == invoice.id,
                JournalEntry.is_reversed == false(),
                JournalEntry.is_deleted == false(),
            )
            .order_by(JournalEntry.id)
            .all()
        )
        for entry in entries:
            # post_journal_entry refuses an unbalanced entry — never bypass it.
            AccountingService.post_journal_entry(
                session,
                date=entry.date,
                reference_type=reversal_ref_type,
                reference_id=invoice.id,
                lines=[
                    {"account_id": jl.account_id, "debit": jl.credit, "credit": jl.debit}
                    for jl in entry.lines
                    if not jl.is_deleted
                ],
                narration=f"Reversal of journal #{entry.id} — {reason_text}",
                created_by=user,
            )
            entry.is_reversed = True
            entry.modified_by = user

    @staticmethod
    def _gst_filed_check(session, invoice_date, verb: str) -> str | None:
        """Block an action on an invoice in a period whose GSTR-1 is filed.

        Raises when the invoice is dated on or before the "GST returns filed up
        to" date. When that date has never been set, returns a warning instead
        — the software cannot know what was filed, so the user must confirm.
        """
        filed_upto = SettingsService.get_gst_filed_upto_date(session)
        if filed_upto is None:
            return (
                "The 'GST returns filed up to' date has never been set (Settings), so the "
                f"software cannot check this. Confirm GSTR-1 for "
                f"{invoice_date.strftime('%B %Y')} has NOT been filed before {verb} — "
                "once filed, the correct route is a credit note."
            )
        if invoice_date <= filed_upto:
            raise ValueError(
                GST_FILED_MESSAGE.format(upto=filed_upto.strftime("%d-%m-%Y"), verb=verb)
            )
        return None

    def _check_edit(self, session, invoice, new_data, reason, modified_by) -> list[str]:
        """Blocking checks (raise) then warnings (returned). Writes nothing."""
        try:
            AuthService.require_role(session, modified_by, INVOICE_EDIT_ROLES, "edit a saved invoice")
        except PermissionError:
            raise InvoiceEditPermissionError(
                "Only an Administrator or Accountant can edit a saved invoice."
            )

        if not reason or not reason.strip():
            raise ValueError("A reason for the edit is required.")

        new_no = new_data.get("invoice_no")
        if new_no is not None and new_no.strip() != invoice.invoice_no:
            raise ValueError(
                f"The invoice number cannot be changed (it is '{invoice.invoice_no}'). "
                "It is the legal document number."
            )

        if not new_data.get("lines"):
            raise ValueError(NO_LINES_MESSAGE)

        original_date = invoice.date
        new_date = new_data.get("date") or original_date
        if (new_date.year, new_date.month) != (original_date.year, original_date.month):
            raise ValueError(
                "The invoice date can only be changed within the same month "
                f"({original_date.strftime('%B %Y')}). Moving a sale to another month "
                "moves it between GST return periods — issue a credit note and a new "
                "invoice instead."
            )

        # Both the date being changed FROM and TO must be open.
        lock = PeriodLockService()
        lock.check_not_locked(original_date)
        lock.check_not_locked(new_date)

        customer_id = new_data.get("customer_id") or invoice.customer_id
        customer = session.get(Customer, customer_id)
        if customer is None or customer.is_deleted:
            raise ValueError(f"Customer {customer_id} not found")

        warnings = []
        today = date_type.today()
        if (original_date.year, original_date.month) < (today.year, today.month):
            warnings.append(
                f"This invoice is dated {original_date.strftime('%d-%m-%Y')}, in an earlier "
                "month. If the GST return for that month has already been filed, the correct "
                "fix is a credit note or debit note, not an edit."
            )
        if customer.id != invoice.customer_id:
            warnings.append(
                f"The customer is changing from '{invoice.customer.name}' to '{customer.name}'. "
                "The customer is a core field of a tax invoice. The original customer's "
                "ledger will be credited back and the new customer debited, and GST will be "
                "recalculated from the new customer's state."
            )
        received = (
            session.query(func.coalesce(func.sum(Receipt.amount), 0))
            .filter(
                Receipt.customer_id == invoice.customer_id,
                Receipt.date >= original_date,
                Receipt.is_deleted == false(),
            )
            .scalar()
        )
        # Receipts are recorded against the customer, not a specific invoice,
        # so any receipt from this customer since the invoice date may be (part
        # of) payment for it.
        if received and float(received) > 0:
            warnings.append(
                f"Receipts of {float(received):.2f} have been recorded from "
                f"'{invoice.customer.name}' since this invoice was dated. If the edit "
                "reduces the invoice below what was received, the customer will be left "
                "with a credit balance."
            )
        return warnings

    @staticmethod
    def _snapshot(invoice) -> dict:
        """The invoice as a JSON-safe dict: header and ACTIVE lines only."""
        return {
            "invoice_no": invoice.invoice_no,
            "status": invoice.status,
            "date": invoice.date.isoformat(),
            "customer_id": invoice.customer_id,
            "customer_name": invoice.customer.name,
            "taxable_amount": str(invoice.taxable_amount),
            "cgst": str(invoice.cgst),
            "sgst": str(invoice.sgst),
            "igst": str(invoice.igst),
            "total": str(invoice.total),
            "lines": [
                {
                    "item_id": line.item_id,
                    "item_code": line.item.code,
                    "quantity": str(line.quantity),
                    "rate": str(line.rate),
                    "amount": str(line.amount),
                    "gst_amount": str(line.gst_amount),
                }
                for line in invoice.items
                if not line.is_deleted
            ],
        }

    # ----- cancel a saved invoice (patch v1.2.0, D1) ----------------------

    def preview_cancellation(self, invoice_id: int, reason: str, cancelled_by: str | None) -> list[str]:
        """Every cancellation check WITHOUT writing: raises for anything that
        blocks, returns the warnings the user must confirm first."""
        session = get_session()
        try:
            invoice = self._load_editable_invoice(session, invoice_id)
            return self._check_cancel(session, invoice, reason, cancelled_by)
        finally:
            session.close()

    def cancel_invoice(self, invoice_id: int, reason: str, cancelled_by: str | None) -> SalesInvoice:
        """Cancel (void) a saved sales invoice. Never a delete.

        All in ONE transaction:
          1. load + every guard (_check_cancel) — before any write
          2. snapshot the invoice as it was
          3-4. reverse every stock row and journal entry still in force
               (_reverse_postings, ref SALE_CANCELLATION, dated like the
               originals). Because only rows with is_reversed False are
               reversed, an invoice edited earlier reverses just the lines in
               force now — not the superseded ones.
          5. status CANCELLED + who/when/why
          6. the line items are NOT soft-deleted — the invoice stays fully
             readable, so an auditor asking about it sees what it contained
          7. audit row, action CANCEL, both snapshots
          8. commit — or roll ALL of it back
        The number stays consumed: the UNIQUE(invoice_no) constraint covers
        cancelled rows too, so it can never be reused.

        Returns the invoice with the confirmed ``cancel_warnings`` attached.
        """
        session = get_session()
        try:
            invoice = self._load_editable_invoice(session, invoice_id)
            warnings = self._check_cancel(session, invoice, reason, cancelled_by)
            before = self._snapshot(invoice)

            self._reverse_postings(
                session, invoice, REF_SALE_CANCELLATION,
                f"cancellation of Sales Invoice {invoice.invoice_no}", cancelled_by,
            )

            now = datetime.utcnow()
            invoice.status = STATUS_CANCELLED
            invoice.cancelled_date = now
            invoice.cancelled_by = cancelled_by
            invoice.cancellation_reason = reason.strip()[:500]
            invoice.modified_by = cancelled_by
            session.flush()

            session.add(
                SalesInvoiceAudit(
                    invoice_id=invoice.id,
                    action=ACTION_CANCEL,
                    edited_by=cancelled_by,
                    edited_date=now,
                    reason=reason.strip()[:500],
                    before_snapshot=json.dumps(before),
                    after_snapshot=json.dumps(self._snapshot(invoice)),
                    created_by=cancelled_by,
                )
            )

            session.commit()
            session.refresh(invoice)
            invoice.cancel_warnings = warnings
            logger.info(
                "Cancelled invoice %s by %s: %s", invoice.invoice_no, cancelled_by, reason.strip()
            )
            return invoice
        except Exception:
            session.rollback()
            logger.exception("Failed to cancel invoice %s", invoice_id)
            raise
        finally:
            session.close()

    def _check_cancel(self, session, invoice, reason, cancelled_by) -> list[str]:
        """Blocking checks (raise) then warnings (returned). Writes nothing.
        (Already-cancelled is refused by _load_editable_invoice.)"""
        AuthService.require_role(session, cancelled_by, INVOICE_CANCEL_ROLES, "cancel an invoice")
        if not reason or not reason.strip():
            raise ValueError("A reason for the cancellation is required.")

        warnings = []
        gst_warning = self._gst_filed_check(session, invoice.date, "cancelling")
        if gst_warning:
            warnings.append(gst_warning)
        PeriodLockService().check_not_locked(invoice.date)

        # Receipts are recorded against the customer, not a specific invoice,
        # so "money against this invoice" is judged from the customer's ledger:
        # what it will read once this invoice's debit is reversed.
        received = self._receipts_since(session, invoice.customer_id, invoice.date)
        if received > 0:
            ledger = invoice.customer.ledger_account
            balance_after = (
                AccountingService.get_account_balance(session, ledger.id) - float(invoice.total)
                if ledger is not None else 0.0
            )
            if balance_after < -0.005:
                warnings.append(
                    f"Rs {-balance_after:,.2f} received from {invoice.customer.name} is not "
                    f"covered by their other invoices. Cancelling this invoice will leave the "
                    f"customer with a credit balance of Rs {-balance_after:,.2f}, to be refunded "
                    "or set against a future sale."
                )
            else:
                warnings.append(
                    f"Receipts of Rs {received:,.2f} have been recorded from "
                    f"{invoice.customer.name} since this invoice was dated. Their other invoices "
                    "still cover what was received, so no credit balance will arise — but check "
                    "the receipt was not meant for this invoice."
                )
        return warnings

    @staticmethod
    def _receipts_since(session, customer_id: int, since) -> float:
        received = (
            session.query(func.coalesce(func.sum(Receipt.amount), 0))
            .filter(
                Receipt.customer_id == customer_id,
                Receipt.date >= since,
                Receipt.is_deleted == false(),
            )
            .scalar()
        )
        return float(received or 0)

    # ----- correct a mistyped invoice number (patch v1.2.0, D2) ------------

    def preview_number_correction(
        self, invoice_id: int, new_invoice_no: str, reason: str, modified_by: str | None
    ) -> list[str]:
        """Every number-correction check WITHOUT writing; returns warnings."""
        session = get_session()
        try:
            invoice = self._load_editable_invoice(session, invoice_id)
            _new_no, warnings = self._check_number_correction(
                session, invoice, new_invoice_no, reason, modified_by
            )
            return warnings
        finally:
            session.close()

    def correct_invoice_number(
        self, invoice_id: int, new_invoice_no: str, reason: str, modified_by: str | None
    ) -> SalesInvoice:
        """Fix a mistyped invoice number. ONE transaction; a label change only.

        Nothing about stock or accounting changes: no stock rows are written
        or touched, and journal amounts and dates are untouched. Only the
        NARRATION of this invoice's journal entries is rewritten where it
        names the old number, so the Day Book and ledgers read correctly.
        Audit row action NUMBER_CORRECTION with both snapshots.

        The cleaner fix for a typo than cancel + re-enter, which would leave a
        cancelled invoice under a number that never existed in the bill book.
        """
        session = get_session()
        try:
            invoice = self._load_editable_invoice(session, invoice_id)
            new_no, warnings = self._check_number_correction(
                session, invoice, new_invoice_no, reason, modified_by
            )
            before = self._snapshot(invoice)
            old_no = invoice.invoice_no

            invoice.invoice_no = new_no
            invoice.modified_by = modified_by

            # Rewrite "Sales Invoice <old>" in the narrations of every journal
            # entry tied to this invoice (the sale, and any edit reversals).
            # Bounded so "INV1" never matches inside "INV10".
            pattern = re.compile(r"(Sales Invoice )" + re.escape(old_no) + r"(?![A-Za-z0-9/-])")
            entries = (
                session.query(JournalEntry)
                .filter(
                    JournalEntry.reference_id == invoice.id,
                    JournalEntry.reference_type.in_(
                        [REF_SALE, REF_SALE_EDIT_REVERSAL, REF_SALE_CANCELLATION]
                    ),
                    JournalEntry.is_deleted == false(),
                )
                .all()
            )
            for entry in entries:
                if entry.narration:
                    updated = pattern.sub(lambda m: m.group(1) + new_no, entry.narration)
                    if updated != entry.narration:
                        entry.narration = updated[:300]
                        entry.modified_by = modified_by

            session.flush()
            session.add(
                SalesInvoiceAudit(
                    invoice_id=invoice.id,
                    action=ACTION_NUMBER_CORRECTION,
                    edited_by=modified_by,
                    edited_date=datetime.utcnow(),
                    reason=reason.strip()[:500],
                    before_snapshot=json.dumps(before),
                    after_snapshot=json.dumps(self._snapshot(invoice)),
                    created_by=modified_by,
                )
            )
            session.commit()
            session.refresh(invoice)
            invoice.correction_warnings = warnings
            logger.info(
                "Invoice number corrected %s -> %s by %s: %s",
                old_no, new_no, modified_by, reason.strip(),
            )
            return invoice
        except IntegrityError:
            session.rollback()
            raise ValueError(
                f"Invoice number '{new_invoice_no}' is already used. Please use a different number."
            )
        except Exception:
            session.rollback()
            logger.exception("Failed to correct the number of invoice %s", invoice_id)
            raise
        finally:
            session.close()

    def _check_number_correction(self, session, invoice, new_invoice_no, reason, modified_by):
        """Blocking checks (raise) then warnings. Returns (clean number, warnings)."""
        AuthService.require_role(
            session, modified_by, INVOICE_CANCEL_ROLES, "correct an invoice number"
        )
        if not reason or not reason.strip():
            raise ValueError("A reason for the correction is required.")
        new_no = validate_invoice_no(new_invoice_no)
        if new_no == invoice.invoice_no:
            raise ValueError("The new invoice number is the same as the current one.")
        # Every invoice counts, CANCELLED ones included: a cancelled number is
        # consumed for good. Case-insensitive, matching SQL Server's default
        # collation, so the check behaves the same on both backends.
        clash = (
            session.query(SalesInvoice.invoice_no, SalesInvoice.status)
            .filter(
                func.upper(SalesInvoice.invoice_no) == new_no.upper(),
                SalesInvoice.id != invoice.id,
            )
            .first()
        )
        if clash is not None:
            held_by = " (a cancelled invoice — cancelled numbers are never reused)" \
                if clash.status == STATUS_CANCELLED else ""
            raise ValueError(f"Invoice number '{clash.invoice_no}' is already used{held_by}.")

        warnings = []
        gst_warning = self._gst_filed_check(session, invoice.date, "renumbering it")
        if gst_warning:
            warnings.append(gst_warning)
        PeriodLockService().check_not_locked(invoice.date)
        return new_no, warnings

    # ----- audit reports (patch v1.2.0, D3) ---------------------------------

    def list_cancelled_invoices(
        self, date_from: date_type | None = None, date_to: date_type | None = None
    ) -> list[dict]:
        """Cancelled invoices by invoice date — what you hand an auditor who
        asks about a missing-looking number: what it was, who cancelled it,
        when and why."""
        session = get_session()
        try:
            query = session.query(SalesInvoice).filter(
                SalesInvoice.status == STATUS_CANCELLED,
                SalesInvoice.is_deleted == false(),
            )
            if date_from:
                query = query.filter(SalesInvoice.date >= date_from)
            if date_to:
                query = query.filter(SalesInvoice.date <= date_to)
            return [
                {
                    "id": inv.id,
                    "invoice_no": inv.invoice_no,
                    "date": inv.date,
                    "customer_name": inv.customer.name,
                    "customer_gstin": inv.customer.gstin,
                    "taxable_amount": float(inv.taxable_amount),
                    "cgst": float(inv.cgst),
                    "sgst": float(inv.sgst),
                    "igst": float(inv.igst),
                    "total": float(inv.total),
                    "cancelled_by": inv.cancelled_by,
                    "cancelled_date": inv.cancelled_date,
                    "cancellation_reason": inv.cancellation_reason,
                }
                for inv in query.order_by(SalesInvoice.date, SalesInvoice.id).all()
            ]
        except Exception:
            logger.exception("Failed to list cancelled invoices")
            raise
        finally:
            session.close()

    def check_invoice_sequence(self, date_from: date_type, date_to: date_type) -> dict:
        """Find missing numbers in the invoice series for a date range.

        Cancelled invoices count as present — they stay in the sequence — so
        used properly this should report no gaps. See find_sequence_gaps().
        """
        session = get_session()
        try:
            numbers = [
                no for (no,) in session.query(SalesInvoice.invoice_no).filter(
                    SalesInvoice.date >= date_from,
                    SalesInvoice.date <= date_to,
                    SalesInvoice.is_deleted == false(),
                )
            ]
        finally:
            session.close()
        return find_sequence_gaps(numbers)

    def get_edit_history(self, invoice_id: int) -> list[dict]:
        """Every change to an invoice, oldest first — edits, a cancellation,
        number corrections (``action``): who, when, why, and the before/after
        snapshots."""
        session = get_session()
        try:
            rows = (
                session.query(SalesInvoiceAudit)
                .filter(
                    SalesInvoiceAudit.invoice_id == invoice_id,
                    SalesInvoiceAudit.is_deleted == false(),
                )
                .order_by(SalesInvoiceAudit.id)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "action": r.action or ACTION_EDIT,
                    "edited_by": r.edited_by,
                    "edited_date": r.edited_date,
                    "reason": r.reason,
                    "before": json.loads(r.before_snapshot) if r.before_snapshot else None,
                    "after": json.loads(r.after_snapshot) if r.after_snapshot else None,
                }
                for r in rows
            ]
        except Exception:
            logger.exception("Failed to load edit history for invoice %s", invoice_id)
            raise
        finally:
            session.close()

    # ----- stock warnings -------------------------------------------------

    @staticmethod
    def _negative_stock_warnings(session, items_sold: dict[int, list]) -> list[str]:
        """Return a warning per item whose stock is below zero after the sale."""
        warnings = []
        for item, _qty in items_sold.values():
            stock = SalesService._current_stock(session, item)
            if stock < 0:
                warnings.append(
                    f"Stock for {item.code} ({item.name}) is now {stock:g} (below zero)."
                )
        return warnings

    @staticmethod
    def _current_stock(session, item) -> float:
        """current_stock = opening_stock + sum(IN) - sum(OUT), backend-neutral."""
        in_qty, out_qty = (
            session.query(
                func.coalesce(
                    func.sum(case((StockTransaction.type == "IN", StockTransaction.quantity), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((StockTransaction.type == "OUT", StockTransaction.quantity), else_=0)), 0
                ),
            )
            .filter(StockTransaction.item_id == item.id, StockTransaction.is_deleted == false())
            .one()
        )
        return float(item.opening_stock) + float(in_qty) - float(out_qty)

    # ----- read ------------------------------------------------------------

    def list_invoices(self, include_cancelled: bool = True) -> list[dict]:
        """Invoices newest first, each with its ``status``.

        Cancelled invoices are included by default — a document listing must
        show that a number exists and is void. Anything that SUMS sales (e.g.
        a dashboard "sales today") must pass include_cancelled=False.
        """
        session = get_session()
        try:
            query = session.query(SalesInvoice).filter(SalesInvoice.is_deleted == false())
            if not include_cancelled:
                query = query.filter(SalesInvoice.status == STATUS_ACTIVE)
            invoices = query.order_by(SalesInvoice.date.desc(), SalesInvoice.id.desc()).all()
            return [
                {
                    "id": inv.id,
                    "invoice_no": inv.invoice_no,
                    "date": inv.date,
                    "customer_name": inv.customer.name,
                    "taxable_amount": float(inv.taxable_amount),
                    "cgst": float(inv.cgst),
                    "sgst": float(inv.sgst),
                    "igst": float(inv.igst),
                    "total": float(inv.total),
                    "edit_count": inv.edit_count or 0,
                    "status": inv.status,
                }
                for inv in invoices
            ]
        except Exception:
            logger.exception("Failed to list invoices")
            raise
        finally:
            session.close()

    def get_invoice_details(self, invoice_id: int) -> dict:
        session = get_session()
        try:
            invoice = session.get(SalesInvoice, invoice_id)
            if invoice is None:
                raise ValueError(f"Invoice {invoice_id} not found")

            return {
                "id": invoice.id,
                "invoice_no": invoice.invoice_no,
                "date": invoice.date,
                "customer_id": invoice.customer_id,
                "customer_name": invoice.customer.name,
                "customer_gstin": invoice.customer.gstin,
                "customer_state": invoice.customer.state,
                "taxable_amount": float(invoice.taxable_amount),
                "cgst": float(invoice.cgst),
                "sgst": float(invoice.sgst),
                "igst": float(invoice.igst),
                "total": float(invoice.total),
                "edit_count": invoice.edit_count or 0,
                "last_edited_date": invoice.last_edited_date,
                "status": invoice.status,
                "cancelled_date": invoice.cancelled_date,
                "cancelled_by": invoice.cancelled_by,
                "cancellation_reason": invoice.cancellation_reason,
                # Only the current lines: an edit soft-deletes the old ones.
                # item_id/gst_rate let the edit screen rebuild them.
                "lines": [
                    {
                        "item_id": line.item_id,
                        "item_code": line.item.code,
                        "item_name": line.item.name,
                        "gst_rate": float(line.item.gst_rate),
                        "quantity": float(line.quantity),
                        "rate": float(line.rate),
                        "amount": float(line.amount),
                        "gst_amount": float(line.gst_amount),
                    }
                    for line in invoice.items
                    if not line.is_deleted
                ],
            }
        except Exception:
            logger.exception("Failed to get details for invoice %s", invoice_id)
            raise
        finally:
            session.close()


def find_sequence_gaps(invoice_numbers: list[str], max_listed: int = 500) -> dict:
    """Find missing serial numbers in a set of invoice numbers.

    Invoice numbers are free text ("105", "INV-105", "DA001/2026-2027"), so
    each number is split into its digit runs. Numbers with the same shape
    (same text around the digits, same count of digit runs) form a family;
    within a family the serial is the digit run that varies most, and the
    other runs (e.g. a financial-year suffix) separate one series from the
    next. Within each series every integer between the lowest and highest
    serial must be present.

    Returns {"series": [...], "gaps": [{"series", "missing", "count"}],
    "unchecked": [numbers with no digits]}. Each gap lists the missing numbers
    formatted like their neighbours (zero padding kept), compressed into
    ranges such as "106-108".
    """
    families: dict[tuple, list[tuple[str, list[str]]]] = {}
    unchecked = []
    for number in sorted(set(invoice_numbers)):
        parts = re.split(r"(\d+)", number)
        texts, runs = tuple(parts[0::2]), parts[1::2]
        if not runs:
            unchecked.append(number)
            continue
        families.setdefault(texts, []).append((number, runs))

    series_out, gaps = [], []
    for texts, members in families.items():
        run_count = len(members[0][1])
        serial_index = max(
            range(run_count),
            key=lambda i: (len({runs[i] for _n, runs in members}), i),
        )
        by_series: dict[tuple, list[str]] = {}
        for _number, runs in members:
            key = tuple(r for i, r in enumerate(runs) if i != serial_index)
            by_series.setdefault(key, []).append(runs[serial_index])

        for key, serials in by_series.items():
            width = min(len(v) for v in serials)
            values = sorted({int(v) for v in serials})

            def label(serial, key=key):
                fixed = iter(key)
                pieces = []
                for i in range(run_count):
                    pieces.append(texts[i])
                    pieces.append(str(serial).zfill(width) if i == serial_index else next(fixed))
                pieces.append(texts[run_count])
                return "".join(pieces)

            name = label("#" * width)
            missing = sorted(set(range(values[0], values[-1] + 1)) - set(values))
            series_out.append({
                "series": name,
                "first": label(values[0]),
                "last": label(values[-1]),
                "count": len(values),
                "missing_count": len(missing),
            })
            if missing:
                ranges, start = [], missing[0]
                for prev, cur in zip(missing, missing[1:] + [None]):
                    if cur != prev + 1:
                        ranges.append(label(start) if start == prev else f"{label(start)} to {label(prev)}")
                        start = cur
                gaps.append({
                    "series": name,
                    "missing": ranges[:max_listed],
                    "count": len(missing),
                })
    series_out.sort(key=lambda r: r["series"])
    gaps.sort(key=lambda r: r["series"])
    return {"series": series_out, "gaps": gaps, "unchecked": unchecked}
