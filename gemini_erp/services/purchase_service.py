"""Business logic for purchase invoices.

create_purchase_invoice() saves the invoice header, its line items, and one
IN stock_transaction per line, all inside a single database transaction
(see CLAUDE.md - "One transaction = all or nothing"). This is the mirror
image of SalesService.create_invoice().
"""

import logging
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal

from database import get_session
from models import Item, PurchaseInvoice, PurchaseInvoiceItem, StockTransaction, Supplier
from services.accounting_service import AccountingService
from services.gst_service import split_gst

logger = logging.getLogger(__name__)


class PurchaseService:
    """Record purchase invoices with automatic stock addition and GST split."""

    def create_purchase_invoice(
        self,
        invoice_no: str,
        invoice_date: date_type,
        supplier_id: int,
        lines: list[dict],
        created_by: str | None = None,
    ) -> PurchaseInvoice:
        """lines: list of {"item_id": int, "quantity": Decimal-like, "rate": Decimal-like}."""
        if not lines:
            raise ValueError("A purchase invoice must have at least one line item")

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

            total_taxable = total_cgst = total_sgst = total_igst = Decimal("0")

            for line in lines:
                item = session.get(Item, line["item_id"])
                if item is None:
                    raise ValueError(f"Item {line['item_id']} not found")

                quantity = Decimal(str(line["quantity"]))
                rate = Decimal(str(line["rate"]))
                amount = (quantity * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                cgst, sgst, igst = split_gst(amount, item.gst_rate, supplier.state)
                gst_amount = cgst + sgst + igst

                session.add(
                    PurchaseInvoiceItem(
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
                        type="IN",
                        quantity=quantity,
                        reference_type="PURCHASE",
                        reference_id=invoice.id,
                        date=invoice_date,
                        created_by=created_by,
                    )
                )

                total_taxable += amount
                total_cgst += cgst
                total_sgst += sgst
                total_igst += igst

            invoice.taxable_amount = total_taxable
            invoice.cgst = total_cgst
            invoice.sgst = total_sgst
            invoice.igst = total_igst
            invoice.total = total_taxable + total_cgst + total_sgst + total_igst

            # --- accounting journal entry ---
            supp_ledger = supplier.ledger_account
            if supp_ledger is None:
                raise ValueError(
                    f"Supplier {supplier_id} has no linked ledger account. "
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
                narration=f"Purchase Invoice {invoice_no}",
                created_by=created_by,
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

    def list_purchase_invoices(self) -> list[dict]:
        session = get_session()
        try:
            invoices = (
                session.query(PurchaseInvoice)
                .filter(PurchaseInvoice.is_deleted.is_(False))
                .order_by(PurchaseInvoice.date.desc(), PurchaseInvoice.id.desc())
                .all()
            )
            return [
                {
                    "id": inv.id,
                    "invoice_no": inv.invoice_no,
                    "date": inv.date,
                    "supplier_name": inv.supplier.name,
                    "taxable_amount": float(inv.taxable_amount),
                    "cgst": float(inv.cgst),
                    "sgst": float(inv.sgst),
                    "igst": float(inv.igst),
                    "total": float(inv.total),
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

            return {
                "id": invoice.id,
                "invoice_no": invoice.invoice_no,
                "date": invoice.date,
                "supplier_name": invoice.supplier.name,
                "supplier_gstin": invoice.supplier.gstin,
                "supplier_state": invoice.supplier.state,
                "taxable_amount": float(invoice.taxable_amount),
                "cgst": float(invoice.cgst),
                "sgst": float(invoice.sgst),
                "igst": float(invoice.igst),
                "total": float(invoice.total),
                "lines": [
                    {
                        "item_code": line.item.code,
                        "item_name": line.item.name,
                        "quantity": float(line.quantity),
                        "rate": float(line.rate),
                        "amount": float(line.amount),
                        "gst_amount": float(line.gst_amount),
                    }
                    for line in invoice.items
                ],
            }
        except Exception:
            logger.exception("Failed to get details for purchase invoice %s", invoice_id)
            raise
        finally:
            session.close()
