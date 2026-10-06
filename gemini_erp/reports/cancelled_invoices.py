"""Cancelled Invoices report and Invoice Sequence Check — Excel / PDF
(patch v1.2.0, D3).

The Cancelled Invoices report is what you hand an auditor who asks about a
number that looks missing: what it was, who cancelled it, when and why.
Renders rows exactly as SalesService returns them; the only arithmetic here is
the column totals on the last row.
"""

import logging
from datetime import date as date_type
from datetime import datetime
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)

# (header, row key, is_amount, PDF width in mm)
COLUMNS = [
    ("Invoice Date", "date", False, 20),
    ("Invoice No", "invoice_no", False, 26),
    ("Customer", "customer_name", False, 42),
    ("GSTIN", "customer_gstin", False, 30),
    ("Taxable", "taxable_amount", True, 20),
    ("GST", "gst", True, 18),
    ("Total", "total", True, 20),
    ("Cancelled By", "cancelled_by", False, 22),
    ("Cancelled On", "cancelled_date", False, 22),
    ("Reason", "cancellation_reason", False, 61),
]


def _value(row: dict, key: str):
    if key == "gst":
        return round(row["cgst"] + row["sgst"] + row["igst"], 2)
    value = row.get(key)
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y %H:%M")
    if isinstance(value, date_type):
        return value.strftime("%d-%m-%Y")
    return "" if value is None else value


def _totals(rows: list[dict]) -> dict:
    return {
        key: round(sum(_value(r, key) for r in rows), 2)
        for _h, key, is_amount, _w in COLUMNS if is_amount
    }


def export_excel(rows: list[dict], path: str, title: str) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cancelled Invoices"
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([h for h, _k, _a, _w in COLUMNS])
    for cell in ws[2]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDDDDD")
    for row in rows:
        ws.append([_value(row, key) for _h, key, _a, _w in COLUMNS])
    totals = _totals(rows)
    ws.append(["Total"] + [totals.get(key, "") for _h, key, _a, _w in COLUMNS[1:]])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    for index, (_h, _key, is_amount, width) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = max(12, width * 0.6)
        if is_amount:
            for (cell,) in ws.iter_rows(min_row=3, min_col=index, max_col=index):
                cell.number_format = "#,##0.00"
    wb.save(path)
    logger.info("Cancelled invoices report (%d rows) exported to %s", len(rows), path)
    return path


def export_pdf(rows: list[dict], path: str, title: str) -> str:
    styles = getSampleStyleSheet()
    small = styles["Normal"].clone("Small", fontSize=7, leading=8)
    data = [[h for h, _k, _a, _w in COLUMNS]]
    for row in rows:
        data.append([
            f"{_value(row, key):,.2f}" if is_amount else Paragraph(escape(str(_value(row, key))), small)
            for _h, key, is_amount, _w in COLUMNS
        ])
    totals = _totals(rows)
    data.append(["Total"] + [
        f"{totals[key]:,.2f}" if is_amount else "" for _h, key, is_amount, _w in COLUMNS[1:]
    ])
    table = Table(data, colWidths=[w * mm for _h, _k, _a, w in COLUMNS], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (4, 1), (6, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    doc = SimpleDocTemplate(
        path, pagesize=landscape(A4),
        leftMargin=8 * mm, rightMargin=8 * mm, topMargin=10 * mm, bottomMargin=10 * mm,
    )
    doc.build([Paragraph(escape(title), styles["Heading3"]), Spacer(1, 3 * mm), table])
    logger.info("Cancelled invoices report (%d rows) exported to %s", len(rows), path)
    return path


def export_sequence_excel(result: dict, path: str, title: str) -> str:
    """The Invoice Sequence Check as a workbook: one sheet per section."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Series"
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append(["Series", "First", "Last", "Invoices", "Missing"])
    for r in result["series"]:
        ws.append([r["series"], r["first"], r["last"], r["count"], r["missing_count"]])
    gaps = wb.create_sheet("Missing numbers")
    gaps.append(["Series", "Missing number(s)"])
    for gap in result["gaps"]:
        for missing in gap["missing"]:
            gaps.append([gap["series"], missing])
    if result["unchecked"]:
        other = wb.create_sheet("Not checked")
        other.append(["Invoice numbers with no digits (cannot be sequence-checked)"])
        for number in result["unchecked"]:
            other.append([number])
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(min_row=1, max_row=2):
            for cell in row:
                cell.font = Font(bold=True)
        sheet.column_dimensions["A"].width = 30
        sheet.column_dimensions["B"].width = 34
    wb.save(path)
    return path
