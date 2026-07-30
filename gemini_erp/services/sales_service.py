"""Business logic for sales invoices.

create_invoice() saves the invoice header, its line items, and one OUT
stock_transaction per line, all inside a single database transaction
(see CLAUDE.md - "One transaction = all or nothing").
"""

import logging
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import false, true
from database import get_session
from models import Customer, Item, SalesInvoice, SalesInvoiceItem, StockTransaction
from services.accounting_service import AccountingService
from services.gst_service import split_gst

logger = logging.getLogger(__name__)


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

            total_taxable = total_cgst = total_sgst = total_igst = Decimal("0")

            for line in lines:
                item = session.get(Item, line["item_id"])
                if item is None:
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
                        reference_type="SALE",
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
            cust_ledger = customer.ledger_account
            if cust_ledger is None:
                raise ValueError(
                    f"Customer {customer_id} has no linked ledger account. "
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
                reference_type="SALE",
                reference_id=invoice.id,
                lines=jnl_lines,
                narration=f"Sales Invoice {invoice_no}",
                created_by=created_by,
            )

            session.commit()
            session.refresh(invoice)
            logger.info("Created invoice %s with %d line(s)", invoice.invoice_no, len(lines))
            return invoice
        except Exception:
            session.rollback()
            logger.exception("Failed to create invoice %s", invoice_no)
            raise
        finally:
            session.close()

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
                "customer_name": invoice.customer.name,
                "customer_gstin": invoice.customer.gstin,
                "customer_state": invoice.customer.state,
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
            logger.exception("Failed to get details for invoice %s", invoice_id)
            raise
        finally:
            session.close()
