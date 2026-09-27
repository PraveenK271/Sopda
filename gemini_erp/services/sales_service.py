"""Business logic for sales invoices.

create_invoice() saves the invoice header, its line items, and one OUT
stock_transaction per line, all inside a single database transaction
(see CLAUDE.md - "One transaction = all or nothing").

update_invoice() (patch v1.1.0, P3) edits a saved invoice by REVERSING its
stock movements and journal entries and RE-POSTING the new ones — nothing is
deleted. See its docstring for why this is the design, and do not "optimise"
it into a diff of old vs new lines.
"""

import json
import logging
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
    User,
)
from services.accounting_service import AccountingService
from services.gst_service import split_gst
from services.period_lock_service import PeriodLockService
from services.permissions import ROLE_ACCOUNTANT, ROLE_ADMINISTRATOR

logger = logging.getLogger(__name__)

# reference_type values for stock_transactions / journal_entries.
REF_SALE = "SALE"
# Both the reversing stock rows and the reversing journal entry of an edit.
REF_SALE_EDIT_REVERSAL = "SALE_EDIT_REVERSAL"

# Only these roles may edit a saved invoice (enforced here, not just in the UI).
INVOICE_EDIT_ROLES = (ROLE_ADMINISTRATOR, ROLE_ACCOUNTANT)

NO_LINES_MESSAGE = (
    "An invoice must have at least one item. To cancel this invoice, issue a credit note."
)


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

            # 4. reverse the stock rows not already reversed — one IN per row.
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
                # No active-item check here: an item soft-deleted from the
                # master since the sale must still get its stock back.
                session.add(
                    StockTransaction(
                        item_id=row.item_id,
                        type="IN",
                        quantity=row.quantity,
                        reference_type=REF_SALE_EDIT_REVERSAL,
                        reference_id=invoice.id,
                        # Dated like the row it cancels (the invoice's date),
                        # not today, so the stock ledger reads right by period.
                        date=row.date,
                        created_by=modified_by,
                    )
                )
                row.is_reversed = True
                row.modified_by = modified_by

            # 5. reverse the journal entries not already reversed.
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
                AccountingService.post_journal_entry(
                    session,
                    date=entry.date,
                    reference_type=REF_SALE_EDIT_REVERSAL,
                    reference_id=invoice.id,
                    lines=[
                        {"account_id": jl.account_id, "debit": jl.credit, "credit": jl.debit}
                        for jl in entry.lines
                        if not jl.is_deleted
                    ],
                    narration=f"Reversal of journal #{entry.id} — edit of Sales Invoice "
                              f"{invoice.invoice_no}",
                    created_by=modified_by,
                )
                entry.is_reversed = True
                entry.modified_by = modified_by

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
        invoice = session.get(SalesInvoice, invoice_id)
        if invoice is None or invoice.is_deleted:
            raise ValueError(f"Invoice {invoice_id} not found")
        return invoice

    def _check_edit(self, session, invoice, new_data, reason, modified_by) -> list[str]:
        """Blocking checks (raise) then warnings (returned). Writes nothing."""
        user = (
            session.query(User)
            .filter(User.username == (modified_by or ""), User.is_deleted == false())
            .first()
        )
        if user is None or not user.is_active or user.role is None \
                or user.role.name not in INVOICE_EDIT_ROLES:
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

    def get_edit_history(self, invoice_id: int) -> list[dict]:
        """Every edit of an invoice, oldest first: who, when, why, and the
        before/after snapshots."""
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

    def list_invoices(self) -> list[dict]:
        session = get_session()
        try:
            invoices = (
                session.query(SalesInvoice)
                .filter(SalesInvoice.is_deleted == false())
                .order_by(SalesInvoice.date.desc(), SalesInvoice.id.desc())
                .all()
            )
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
