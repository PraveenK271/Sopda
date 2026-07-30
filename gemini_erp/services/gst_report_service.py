"""GST reporting: registers, HSN summary, and GSTR-1 / GSTR-3B figures.

This service is a pure read layer over the raw invoice tables — it does NOT
touch the accounting engine (journal entries). It reads sales/purchase
invoices directly, so it also sees pre-Milestone-11 invoices (which have no
journal entries; see CHECKLIST_PHASE2_PART2.md Decision 2). These are the
numbers a user types into the GST portal — no e-filing integration.

Per-line CGST/SGST/IGST split
-----------------------------
Invoices store the tax split only at the header level (`cgst`, `sgst`, `igst`).
Each line stores `amount` (taxable) and `gst_amount` (total tax for the line).
We infer the line's split from the invoice: if the invoice has IGST it is an
inter-state supply, so the whole line tax is IGST; otherwise it splits into
CGST + SGST. We compute `cgst = round(gst_amount / 2)` and
`sgst = gst_amount - cgst` so a line's CGST + SGST always equals its
`gst_amount` exactly (no half-paisa drift when aggregating).
"""

import logging
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import false, true
from database import get_session
from models import (
    Customer,
    Item,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    SalesInvoice,
    SalesInvoiceItem,
    Supplier,
)

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")
SALES = "SALES"
PURCHASE = "PURCHASE"


def _has_gstin(value: str | None) -> bool:
    return bool(value and value.strip())


def _half(amount: Decimal) -> Decimal:
    """First half of a tax amount (CGST). SGST is the remainder, so the two
    always add back to `amount` exactly."""
    return (amount / 2).quantize(_CENT, rounding=ROUND_HALF_UP)


class GstReportService:
    """Sales/purchase registers, HSN summary, GSTR-1 and GSTR-3B figures."""

    # ----- shared line extraction ---------------------------------------

    @staticmethod
    def _line_rows(session, direction: str, date_from, date_to) -> list[dict]:
        """One dict per invoice line for the period, with the CGST/SGST/IGST
        split resolved. Shared by the registers and the HSN summary."""
        if direction == SALES:
            invoice_cls, line_cls, party_cls = SalesInvoice, SalesInvoiceItem, Customer
            party_fk = SalesInvoice.customer_id
        elif direction == PURCHASE:
            invoice_cls, line_cls, party_cls = PurchaseInvoice, PurchaseInvoiceItem, Supplier
            party_fk = PurchaseInvoice.supplier_id
        else:
            raise ValueError(f"Invalid direction '{direction}' (expected 'SALES' or 'PURCHASE')")

        rows = (
            session.query(line_cls, invoice_cls, party_cls, Item)
            .join(invoice_cls, line_cls.invoice_id == invoice_cls.id)
            .join(party_cls, party_fk == party_cls.id)
            .join(Item, line_cls.item_id == Item.id)
            .filter(
                invoice_cls.date >= date_from,
                invoice_cls.date <= date_to,
                invoice_cls.is_deleted == false(),
                line_cls.is_deleted == false(),
            )
            .order_by(invoice_cls.date, invoice_cls.id, line_cls.id)
            .all()
        )

        result = []
        for line, invoice, party, item in rows:
            taxable = Decimal(str(line.amount))
            gst_amount = Decimal(str(line.gst_amount))
            inter_state = Decimal(str(invoice.igst)) > 0
            if inter_state:
                cgst = sgst = Decimal("0")
                igst = gst_amount
            else:
                cgst = _half(gst_amount)
                sgst = gst_amount - cgst
                igst = Decimal("0")

            result.append({
                "date": invoice.date,
                "invoice_no": invoice.invoice_no,
                "party_name": party.name,
                "party_gstin": party.gstin,
                "hsn_code": item.hsn_code or "",
                "gst_rate": float(item.gst_rate),
                "quantity": float(line.quantity),
                "taxable_amount": float(taxable),
                "cgst": float(cgst),
                "sgst": float(sgst),
                "igst": float(igst),
                "total": float(taxable + gst_amount),
            })
        return result

    # ----- Milestone 18: registers + HSN summary ------------------------

    @staticmethod
    def get_sales_register(date_from: date_type, date_to: date_type) -> list[dict]:
        """One row per sales invoice line in the period."""
        session = get_session()
        try:
            rows = GstReportService._line_rows(session, SALES, date_from, date_to)
            return [
                {
                    "date": r["date"],
                    "invoice_no": r["invoice_no"],
                    "customer_name": r["party_name"],
                    "customer_gstin": r["party_gstin"],
                    "hsn_code": r["hsn_code"],
                    "taxable_amount": r["taxable_amount"],
                    "cgst": r["cgst"],
                    "sgst": r["sgst"],
                    "igst": r["igst"],
                    "total": r["total"],
                }
                for r in rows
            ]
        except Exception:
            logger.exception("Failed to build sales register")
            raise
        finally:
            session.close()

    @staticmethod
    def get_purchase_register(date_from: date_type, date_to: date_type) -> list[dict]:
        """One row per purchase invoice line in the period."""
        session = get_session()
        try:
            rows = GstReportService._line_rows(session, PURCHASE, date_from, date_to)
            return [
                {
                    "date": r["date"],
                    "invoice_no": r["invoice_no"],
                    "supplier_name": r["party_name"],
                    "supplier_gstin": r["party_gstin"],
                    "hsn_code": r["hsn_code"],
                    "taxable_amount": r["taxable_amount"],
                    "cgst": r["cgst"],
                    "sgst": r["sgst"],
                    "igst": r["igst"],
                    "total": r["total"],
                }
                for r in rows
            ]
        except Exception:
            logger.exception("Failed to build purchase register")
            raise
        finally:
            session.close()

    @staticmethod
    def get_hsn_summary(
        date_from: date_type, date_to: date_type, direction: str = SALES
    ) -> list[dict]:
        """Lines grouped by (hsn_code, gst_rate): total qty, taxable, and tax."""
        session = get_session()
        try:
            rows = GstReportService._line_rows(session, direction, date_from, date_to)
            grouped: dict[tuple, dict] = {}
            for r in rows:
                key = (r["hsn_code"], r["gst_rate"])
                g = grouped.setdefault(key, {
                    "hsn_code": r["hsn_code"],
                    "gst_rate": r["gst_rate"],
                    "quantity": 0.0,
                    "taxable_amount": 0.0,
                    "cgst": 0.0,
                    "sgst": 0.0,
                    "igst": 0.0,
                    "total": 0.0,
                })
                for field in ("quantity", "taxable_amount", "cgst", "sgst", "igst", "total"):
                    g[field] = round(g[field] + r[field], 2)

            return sorted(grouped.values(), key=lambda g: (g["hsn_code"], g["gst_rate"]))
        except Exception:
            logger.exception("Failed to build HSN summary")
            raise
        finally:
            session.close()

    # ----- Milestone 19: GSTR-1 / GSTR-3B -------------------------------

    @staticmethod
    def get_gstr1_summary(date_from: date_type, date_to: date_type) -> dict:
        """GSTR-1 outward supplies: B2B (per invoice, registered customers),
        B2C small (aggregated, unregistered customers), plus HSN summary."""
        session = get_session()
        try:
            invoices = (
                session.query(SalesInvoice, Customer)
                .join(Customer, SalesInvoice.customer_id == Customer.id)
                .filter(
                    SalesInvoice.date >= date_from,
                    SalesInvoice.date <= date_to,
                    SalesInvoice.is_deleted == false(),
                )
                .order_by(SalesInvoice.date, SalesInvoice.id)
                .all()
            )

            b2b = []
            b2c_taxable = b2c_cgst = b2c_sgst = b2c_igst = 0.0
            for inv, customer in invoices:
                taxable = float(inv.taxable_amount)
                cgst = float(inv.cgst)
                sgst = float(inv.sgst)
                igst = float(inv.igst)
                if _has_gstin(customer.gstin):
                    b2b.append({
                        "gstin": customer.gstin.strip(),
                        "customer_name": customer.name,
                        "invoice_no": inv.invoice_no,
                        "date": inv.date,
                        "taxable_value": taxable,
                        "cgst": cgst,
                        "sgst": sgst,
                        "igst": igst,
                    })
                else:
                    b2c_taxable += taxable
                    b2c_cgst += cgst
                    b2c_sgst += sgst
                    b2c_igst += igst
        finally:
            session.close()

        return {
            "b2b": b2b,
            "b2c_small": {
                "taxable_value": round(b2c_taxable, 2),
                "cgst": round(b2c_cgst, 2),
                "sgst": round(b2c_sgst, 2),
                "igst": round(b2c_igst, 2),
            },
            "hsn_summary": GstReportService.get_hsn_summary(date_from, date_to, SALES),
        }

    @staticmethod
    def get_gstr3b_summary(date_from: date_type, date_to: date_type) -> dict:
        """GSTR-3B headline figures: outward tax (3.1a), ITC available (table 4),
        and net tax payable per head (output - ITC, floored at 0). Any excess
        ITC per head is reported as itc_carried_forward."""
        session = get_session()
        try:
            outward = GstReportService._invoice_tax_totals(
                session, SalesInvoice, date_from, date_to
            )
            inward = GstReportService._invoice_tax_totals(
                session, PurchaseInvoice, date_from, date_to
            )
        finally:
            session.close()

        net_payable = {}
        carried_forward = {}
        for head in ("cgst", "sgst", "igst"):
            diff = round(outward[head] - inward[head], 2)
            net_payable[head] = diff if diff > 0 else 0.0
            carried_forward[head] = -diff if diff < 0 else 0.0

        return {
            "outward_taxable_supplies": outward,
            "itc_available": {
                "cgst": inward["cgst"],
                "sgst": inward["sgst"],
                "igst": inward["igst"],
            },
            "net_tax_payable": net_payable,
            "itc_carried_forward": carried_forward,
        }

    @staticmethod
    def _invoice_tax_totals(session, invoice_cls, date_from, date_to) -> dict:
        """Sum taxable_amount/cgst/sgst/igst over non-deleted invoices in range."""
        from sqlalchemy import func as sqlfunc

        row = (
            session.query(
                sqlfunc.coalesce(sqlfunc.sum(invoice_cls.taxable_amount), 0),
                sqlfunc.coalesce(sqlfunc.sum(invoice_cls.cgst), 0),
                sqlfunc.coalesce(sqlfunc.sum(invoice_cls.sgst), 0),
                sqlfunc.coalesce(sqlfunc.sum(invoice_cls.igst), 0),
            )
            .filter(
                invoice_cls.date >= date_from,
                invoice_cls.date <= date_to,
                invoice_cls.is_deleted == false(),
            )
            .one()
        )
        return {
            "taxable_amount": round(float(row[0]), 2),
            "cgst": round(float(row[1]), 2),
            "sgst": round(float(row[2]), 2),
            "igst": round(float(row[3]), 2),
        }
