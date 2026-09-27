"""Business logic for purchase invoices.

create_purchase_invoice() saves the invoice header, its line items, and one
IN stock_transaction per line, all inside a single database transaction
(see CLAUDE.md - "One transaction = all or nothing"). This is the mirror
image of SalesService.create_invoice().

Patch v1.1.0 (P2) adds two discounts, both applied BEFORE GST because an
on-invoice discount reduces the taxable value:
- a per-line ``discount_percent`` (the supplier's trade discount), and
- a flat ``special_discount`` off the whole bill, APPORTIONED across the lines in
  proportion to each line's net value, with GST recomputed per line. Simply
  subtracting it from the total would give the wrong CGST/SGST split when lines
  carry different GST rates. See calculate_purchase().
"""

import logging
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import false, true
from database import get_session
from models import (
    Item,
    JournalEntry,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    StockTransaction,
    Supplier,
)
from services.accounting_service import AccountingService
from services.gst_service import split_gst
from services.period_lock_service import PeriodLockService

logger = logging.getLogger(__name__)

_PAISA = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_PAISA, rounding=ROUND_HALF_UP)


def discount_value(value, field_name: str) -> Decimal:
    """A discount input as Decimal. Blank, None or "" means 0 — a missing
    discount is never an error (explicit requirement). Non-numeric text is."""
    if value is None:
        return Decimal("0")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return Decimal("0")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{field_name} must be a number, got '{value}'")


def calculate_purchase(lines: list[dict], special_discount, supplier_state: str | None) -> dict:
    """Price a purchase bill: line discounts, apportioned special discount, GST.

    lines: [{"quantity", "rate", "gst_rate", "discount_percent" (optional)}].
    A pure function: the service uses it to save, and the Purchase screen uses
    it for the live totals panel, so the two can never disagree.

    Order (INSTRUCTIONS_PATCH_V1_1.md, P2):
        line_gross    = quantity x rate
        line_discount = line_gross x discount_percent / 100
        line_net      = line_gross - line_discount
        share         = line_net / invoice_net            (0 if invoice_net is 0)
        apportioned   = round(special_discount x share, 2)
        line_taxable  = line_net - apportioned
        line_gst      = on line_taxable, split by the supplier's state

    The last line with value takes the rounding remainder, so the apportioned
    amounts sum to the special discount exactly, to the paisa. Raises
    ValueError for a discount % outside 0-100, a negative special discount, or
    a special discount larger than the bill's value after line discounts.
    """
    special = _money(discount_value(special_discount, "Special discount"))
    if special < 0:
        raise ValueError("Special discount cannot be negative.")

    priced = []
    for index, line in enumerate(lines, start=1):
        quantity = Decimal(str(line["quantity"]))
        rate = Decimal(str(line["rate"]))
        percent = discount_value(line.get("discount_percent"), f"Discount % on line {index}")
        if percent < 0 or percent > 100:
            raise ValueError(
                f"Discount % on line {index} must be between 0 and 100 (got {percent})."
            )
        gross = _money(quantity * rate)
        line_discount = _money(gross * percent / Decimal("100"))
        priced.append({
            "quantity": quantity,
            "rate": rate,
            "gst_rate": line["gst_rate"],
            "discount_percent": percent,
            "gross": gross,
            "discount_amount": line_discount,
            "net": gross - line_discount,
        })

    invoice_net = sum((p["net"] for p in priced), Decimal("0"))
    if special > invoice_net:
        raise ValueError(
            f"Special discount {special} cannot exceed the bill's value after line "
            f"discounts ({invoice_net})."
        )

    # The remainder goes to the last line that has value to absorb it — a line
    # discounted to zero cannot take a share without going negative.
    last_with_value = max((i for i, p in enumerate(priced) if p["net"] > 0), default=None)
    allocated = Decimal("0")
    for i, p in enumerate(priced):
        if not special or invoice_net == 0:
            apportioned = Decimal("0")
        elif i == last_with_value:
            apportioned = special - allocated
        else:
            apportioned = _money(special * p["net"] / invoice_net)
        allocated += apportioned
        p["apportioned"] = apportioned
        p["taxable"] = p["net"] - apportioned
        p["cgst"], p["sgst"], p["igst"] = split_gst(p["taxable"], p["gst_rate"], supplier_state)
        p["gst_amount"] = p["cgst"] + p["sgst"] + p["igst"]

    totals = {
        key: sum((p[key] for p in priced), Decimal("0"))
        for key in ("gross", "discount_amount", "taxable", "cgst", "sgst", "igst")
    }
    totals["line_discount"] = totals.pop("discount_amount")
    totals["special_discount"] = special
    totals["total_discount"] = totals["line_discount"] + special
    totals["gst"] = totals["cgst"] + totals["sgst"] + totals["igst"]
    totals["total"] = totals["taxable"] + totals["gst"]
    return {"lines": priced, "totals": totals}


class PurchaseService:
    """Record purchase invoices with automatic stock addition and GST split."""

    def create_purchase_invoice(
        self,
        invoice_no: str,
        invoice_date: date_type,
        supplier_id: int,
        lines: list[dict],
        created_by: str | None = None,
        special_discount=None,
    ) -> PurchaseInvoice:
        """lines: list of {"item_id": int, "quantity": Decimal-like, "rate": Decimal-like,
        "discount_percent": optional, blank = 0}. special_discount: optional flat
        rupee amount off the whole bill, blank = 0."""
        if not lines:
            raise ValueError("A purchase invoice must have at least one line item")
        PeriodLockService().check_not_locked(invoice_date)

        session = get_session()
        try:
            supplier = session.get(Supplier, supplier_id)
            if supplier is None:
                raise ValueError(f"Supplier {supplier_id} not found")

            invoice = PurchaseInvoice(
                invoice_no=invoice_no,
                date=invoice_date,
                supplier_id=supplier_id,
                taxable_amount=0,
                cgst=0,
                sgst=0,
                igst=0,
                total=0,
                created_by=created_by,
            )
            session.add(invoice)
            session.flush()  # assign invoice.id within this transaction

            self._apply_lines_and_accounting(
                session, invoice, supplier, lines, invoice_date,
                narration=f"Purchase Invoice {invoice_no}", created_by=created_by,
                special_discount=special_discount,
            )

            session.commit()
            session.refresh(invoice)
            logger.info("Created purchase invoice %s with %d line(s)", invoice.invoice_no, len(lines))
            return invoice
        except Exception:
            session.rollback()
            logger.exception("Failed to create purchase invoice %s", invoice_no)
            raise
        finally:
            session.close()

    def update_purchase_invoice(
        self,
        invoice_id: int,
        invoice_no: str,
        invoice_date: date_type,
        supplier_id: int,
        lines: list[dict],
        modified_by: str | None = None,
        special_discount=None,
    ) -> PurchaseInvoice:
        """Edit a saved purchase invoice, keeping stock and books in sync.

        All in ONE transaction (CLAUDE.md): the original IN stock movements and
        the original journal entry are REVERSED (soft-deleted, never physically
        removed), the old line items are soft-deleted, then the edited header,
        lines, IN movements and a fresh balanced journal entry are re-applied.
        If anything fails the whole edit rolls back, so billing, inventory and
        the ledger can never drift apart.
        """
        if not lines:
            raise ValueError("A purchase invoice must have at least one line item")
        PeriodLockService().check_not_locked(invoice_date)

        session = get_session()
        try:
            invoice = session.get(PurchaseInvoice, invoice_id)
            if invoice is None or invoice.is_deleted:
                raise ValueError(f"Purchase invoice {invoice_id} not found")
            supplier = session.get(Supplier, supplier_id)
            if supplier is None:
                raise ValueError(f"Supplier {supplier_id} not found")

            # --- reverse the original invoice's side effects (soft delete) ---
            for old_line in invoice.items:
                if not old_line.is_deleted:
                    old_line.is_deleted = True
                    old_line.modified_by = modified_by

            old_txns = (
                session.query(StockTransaction)
                .filter(
                    StockTransaction.reference_type == "PURCHASE",
                    StockTransaction.reference_id == invoice_id,
                    StockTransaction.is_deleted == false(),
                )
                .all()
            )
            for txn in old_txns:
                txn.is_deleted = True
                txn.modified_by = modified_by

            old_entries = (
                session.query(JournalEntry)
                .filter(
                    JournalEntry.reference_type == "PURCHASE",
                    JournalEntry.reference_id == invoice_id,
                    JournalEntry.is_deleted == false(),
                )
                .all()
            )
            for entry in old_entries:
                entry.is_deleted = True
                entry.modified_by = modified_by
                for jl in entry.lines:
                    if not jl.is_deleted:
                        jl.is_deleted = True
                        jl.modified_by = modified_by

            # --- re-apply the edited invoice ---
            invoice.invoice_no = invoice_no
            invoice.date = invoice_date
            invoice.supplier_id = supplier_id
            invoice.modified_by = modified_by
            session.flush()

            self._apply_lines_and_accounting(
                session, invoice, supplier, lines, invoice_date,
                narration=f"Purchase Invoice {invoice_no} (edited)", created_by=modified_by,
                special_discount=special_discount,
            )

            session.commit()
            session.refresh(invoice)
            logger.info("Updated purchase invoice %s with %d line(s)", invoice.invoice_no, len(lines))
            return invoice
        except Exception:
            session.rollback()
            logger.exception("Failed to update purchase invoice %s", invoice_id)
            raise
        finally:
            session.close()

    def _apply_lines_and_accounting(
        self, session, invoice, supplier, lines, invoice_date, narration, created_by,
        special_discount=None,
    ) -> None:
        """Create the line items + IN stock movements for `invoice`, set its
        header totals, and post the matching balanced journal entry.

        Shared by create and update so both stay identical: one IN stock
        transaction per line, discounts applied before GST (calculate_purchase),
        GST split by the supplier's state, and a Purchase(Dr) + Input-GST(Dr) /
        Supplier(Cr) entry on the NET figures. On-invoice discounts are part of
        the purchase price, so no separate discount ledger is posted. Operates
        on the caller's session/transaction; never commits.
        """
        items = []
        for line in lines:
            item = session.get(Item, line["item_id"])
            if item is None:
                raise ValueError(f"Item {line['item_id']} not found")
            items.append(item)

        priced = calculate_purchase(
            [
                {
                    "quantity": line["quantity"],
                    "rate": line["rate"],
                    "discount_percent": line.get("discount_percent"),
                    "gst_rate": item.gst_rate,
                }
                for line, item in zip(lines, items)
            ],
            special_discount,
            supplier.state,
        )

        for item, p in zip(items, priced["lines"]):
            session.add(
                PurchaseInvoiceItem(
                    invoice_id=invoice.id,
                    item_id=item.id,
                    quantity=p["quantity"],
                    rate=p["rate"],
                    # amount = the line's taxable value after BOTH discounts, so
                    # the registers/HSN summary read net figures unchanged.
                    amount=p["taxable"],
                    gst_amount=p["gst_amount"],
                    discount_percent=p["discount_percent"],
                    discount_amount=p["discount_amount"],
                    created_by=created_by,
                )
            )
            session.add(
                StockTransaction(
                    item_id=item.id,
                    type="IN",
                    quantity=p["quantity"],
                    reference_type="PURCHASE",
                    reference_id=invoice.id,
                    date=invoice_date,
                    created_by=created_by,
                )
            )

        totals = priced["totals"]
        total_taxable = totals["taxable"]
        total_cgst, total_sgst, total_igst = totals["cgst"], totals["sgst"], totals["igst"]
        invoice.taxable_amount = total_taxable
        invoice.cgst = total_cgst
        invoice.sgst = total_sgst
        invoice.igst = total_igst
        invoice.total = totals["total"]
        invoice.special_discount = totals["special_discount"]
        invoice.total_discount = totals["total_discount"]

        supp_ledger = supplier.ledger_account
        if supp_ledger is None:
            raise ValueError(
                f"Supplier {supplier.id} has no linked ledger account. "
                "Re-add the supplier or run create_db.py to seed accounts."
            )
        purchase_acct = AccountingService.get_account_by_code(session, "PURCHASE")
        jnl_lines = [
            {"account_id": purchase_acct.id, "debit": total_taxable, "credit": Decimal("0")},
        ]
        if total_cgst:
            acct = AccountingService.get_account_by_code(session, "CGST_INPUT")
            jnl_lines.append({"account_id": acct.id, "debit": total_cgst, "credit": Decimal("0")})
        if total_sgst:
            acct = AccountingService.get_account_by_code(session, "SGST_INPUT")
            jnl_lines.append({"account_id": acct.id, "debit": total_sgst, "credit": Decimal("0")})
        if total_igst:
            acct = AccountingService.get_account_by_code(session, "IGST_INPUT")
            jnl_lines.append({"account_id": acct.id, "debit": total_igst, "credit": Decimal("0")})
        jnl_lines.append(
            {"account_id": supp_ledger.id, "debit": Decimal("0"), "credit": invoice.total}
        )
        AccountingService.post_journal_entry(
            session,
            date=invoice_date,
            reference_type="PURCHASE",
            reference_id=invoice.id,
            lines=jnl_lines,
            narration=narration,
            created_by=created_by,
        )

    def list_purchase_invoices(self) -> list[dict]:
        session = get_session()
        try:
            invoices = (
                session.query(PurchaseInvoice)
                .filter(PurchaseInvoice.is_deleted == false())
                .order_by(PurchaseInvoice.date.desc(), PurchaseInvoice.id.desc())
                .all()
            )
            return [
                {
                    "id": inv.id,
                    "invoice_no": inv.invoice_no,
                    "date": inv.date,
                    "supplier_id": inv.supplier_id,
                    "supplier_name": inv.supplier.name,
                    "taxable_amount": float(inv.taxable_amount),
                    "cgst": float(inv.cgst),
                    "sgst": float(inv.sgst),
                    "igst": float(inv.igst),
                    "total": float(inv.total),
                    "total_discount": float(inv.total_discount or 0),
                }
                for inv in invoices
            ]
        except Exception:
            logger.exception("Failed to list purchase invoices")
            raise
        finally:
            session.close()

    def get_purchase_invoice_details(self, invoice_id: int) -> dict:
        session = get_session()
        try:
            invoice = session.get(PurchaseInvoice, invoice_id)
            if invoice is None:
                raise ValueError(f"Purchase invoice {invoice_id} not found")
            # Skip soft-deleted lines (an edit replaces lines by soft-deleting
            # the originals).
            active_lines = [line for line in invoice.items if not line.is_deleted]

            def gross(line) -> Decimal:
                return _money(Decimal(str(line.quantity)) * Decimal(str(line.rate)))

            return {
                "id": invoice.id,
                "invoice_no": invoice.invoice_no,
                "date": invoice.date,
                "supplier_id": invoice.supplier_id,
                "supplier_name": invoice.supplier.name,
                "supplier_gstin": invoice.supplier.gstin,
                "supplier_state": invoice.supplier.state,
                "gross_amount": float(sum((gross(line) for line in active_lines), Decimal("0"))),
                "special_discount": float(invoice.special_discount or 0),
                "total_discount": float(invoice.total_discount or 0),
                "taxable_amount": float(invoice.taxable_amount),
                "cgst": float(invoice.cgst),
                "sgst": float(invoice.sgst),
                "igst": float(invoice.igst),
                "total": float(invoice.total),
                # item_id/gst_rate let the edit screen rebuild the lines.
                # "amount" is the line's taxable value (after all discounts).
                "lines": [
                    {
                        "item_id": line.item_id,
                        "item_code": line.item.code,
                        "item_name": line.item.name,
                        "gst_rate": float(line.item.gst_rate),
                        "quantity": float(line.quantity),
                        "rate": float(line.rate),
                        "gross": float(gross(line)),
                        "discount_percent": float(line.discount_percent or 0),
                        "discount_amount": float(line.discount_amount or 0),
                        "amount": float(line.amount),
                        "gst_amount": float(line.gst_amount),
                    }
                    for line in active_lines
                ],
            }
        except Exception:
            logger.exception("Failed to get details for purchase invoice %s", invoice_id)
            raise
        finally:
            session.close()
