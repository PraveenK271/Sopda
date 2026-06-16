"""Generate a Tax Invoice PDF for a saved sales invoice (ReportLab).

Reads the invoice, its line items, and the customer from the database and
lays them out on an A4 page. This module only renders data that the service
layer has already saved - it does not calculate anything.
"""

import logging

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from database import get_session
from models import SalesInvoice
from reports.amount_in_words import amount_to_words
from reports.company_info import (
    BANK_ACCOUNT_NO,
    BANK_BRANCH,
    BANK_IFSC,
    BANK_NAME,
    COMPANY_ADDRESS,
    COMPANY_GSTIN,
    COMPANY_MOBILE,
    COMPANY_NAME,
    COMPANY_STATE,
    TERMS_AND_CONDITIONS,
)

logger = logging.getLogger(__name__)


def generate_invoice_pdf(invoice_id: int, output_path: str) -> str:
    """Render the given invoice as a PDF and save it to output_path."""
    session = get_session()
    try:
        invoice = session.get(SalesInvoice, invoice_id)
        if invoice is None:
            raise ValueError(f"Invoice {invoice_id} not found")

        customer = invoice.customer
        styles = getSampleStyleSheet()
        center = ParagraphStyle("Center", parent=styles["Normal"], alignment=TA_CENTER)
        company_name_style = ParagraphStyle(
            "CompanyName", parent=styles["Heading2"], alignment=TA_CENTER
        )
        title_style = ParagraphStyle(
            "InvoiceTitle", parent=styles["Heading3"], alignment=TA_CENTER
        )
        right = ParagraphStyle("Right", parent=styles["Normal"], alignment=TA_RIGHT)

        elements = []

        # Seller header
        elements.append(Paragraph(COMPANY_NAME, company_name_style))
        elements.append(Paragraph(COMPANY_ADDRESS, center))
        elements.append(Paragraph(f"Mobile: {COMPANY_MOBILE}", center))
        elements.append(
            Paragraph(f"GSTIN: {COMPANY_GSTIN} | State: {COMPANY_STATE}", center)
        )
        elements.append(Spacer(1, 6 * mm))
        elements.append(Paragraph("TAX INVOICE", title_style))
        elements.append(Spacer(1, 4 * mm))

        # Invoice and customer details
        info_data = [
            ["Invoice No:", invoice.invoice_no, "Date:", invoice.date.strftime("%d-%m-%Y")],
            ["Customer:", customer.name, "GSTIN:", customer.gstin or "-"],
            ["Address:", customer.address or "-", "State:", customer.state or "-"],
        ]
        info_table = Table(info_data, colWidths=[25 * mm, 70 * mm, 20 * mm, 65 * mm])
        info_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        elements.append(info_table)
        elements.append(Spacer(1, 6 * mm))

        # Line items
        header = ["#", "Item Code", "Item Name", "HSN", "Qty", "Unit", "Rate", "Amount", "GST"]
        rows = [header]
        for idx, line in enumerate(invoice.items, start=1):
            item = line.item
            rows.append(
                [
                    str(idx),
                    item.code,
                    item.name,
                    item.hsn_code or "-",
                    f"{line.quantity:.2f}",
                    item.unit or "-",
                    f"{line.rate:.2f}",
                    f"{line.amount:.2f}",
                    f"{line.gst_amount:.2f}",
                ]
            )

        items_table = Table(
            rows,
            colWidths=[8 * mm, 22 * mm, 45 * mm, 18 * mm, 14 * mm, 14 * mm, 20 * mm, 22 * mm, 17 * mm],
            repeatRows=1,
        )
        items_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(items_table)
        elements.append(Spacer(1, 4 * mm))

        # Totals
        totals_rows = [["Taxable Amount", f"{invoice.taxable_amount:.2f}"]]
        if invoice.cgst:
            totals_rows.append(["CGST", f"{invoice.cgst:.2f}"])
        if invoice.sgst:
            totals_rows.append(["SGST", f"{invoice.sgst:.2f}"])
        if invoice.igst:
            totals_rows.append(["IGST", f"{invoice.igst:.2f}"])
        totals_rows.append(["Total", f"{invoice.total:.2f}"])

        totals_table = Table(totals_rows, colWidths=[40 * mm, 30 * mm])
        totals_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
                ]
            )
        )

        # Amount in words + bank details (left) alongside totals (right)
        small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8)
        amount_words_text = (
            f"<b>Amount in Words:</b><br/>{amount_to_words(invoice.total)}<br/><br/>"
            f"<b>Bank Details</b><br/>"
            f"Name: {BANK_NAME}<br/>"
            f"A/c No: {BANK_ACCOUNT_NO}<br/>"
            f"IFSC: {BANK_IFSC}<br/>"
            f"Branch: {BANK_BRANCH}"
        )
        amount_words_para = Paragraph(amount_words_text, small)

        bottom_table = Table([[amount_words_para, totals_table]], colWidths=[110 * mm, 70 * mm])
        bottom_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ]
            )
        )
        elements.append(bottom_table)
        elements.append(Spacer(1, 10 * mm))

        # Terms & conditions (left) and signature area (right)
        terms_items = "<br/>".join(
            f"{idx}. {term}" for idx, term in enumerate(TERMS_AND_CONDITIONS, start=1)
        )
        terms_para = Paragraph(f"<b>Terms &amp; Conditions</b><br/>{terms_items}", small)

        signature_text = f"For {COMPANY_NAME}<br/><br/><br/><br/>Authorised Signatory"
        signature_para = Paragraph(signature_text, right)

        footer_table = Table([[terms_para, signature_para]], colWidths=[110 * mm, 70 * mm])
        footer_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        elements.append(footer_table)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
        )
        doc.build(elements)
        logger.info("Generated PDF for invoice %s at %s", invoice.invoice_no, output_path)
        return output_path
    except Exception:
        logger.exception("Failed to generate PDF for invoice %s", invoice_id)
        raise
    finally:
        session.close()
