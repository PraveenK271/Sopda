"""Invoice audit screens (patch v1.2.0, D3) — under the Sales Log tab.

- Cancelled Invoices: what was cancelled, by whom, when and why; Excel / PDF.
  What you hand an auditor who asks about a number that looks missing.
- Invoice Sequence Check: missing numbers in the series for a date range.
  Cancelled invoices stay in the sequence, so used properly this is empty —
  it proves the no-gaps property rather than assuming it. Run it before filing.

UI only: SalesService does the work; reports/cancelled_invoices.py exports.
"""

import logging

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reports.cancelled_invoices import export_excel, export_pdf, export_sequence_excel
from services.sales_service import SalesService

logger = logging.getLogger(__name__)


def _financial_year_start() -> QDate:
    today = QDate.currentDate()
    year = today.year() if today.month() >= 4 else today.year() - 1
    return QDate(year, 4, 1)


def _date_controls(owner, on_refresh):
    owner.date_from = QDateEdit(_financial_year_start())
    owner.date_from.setCalendarPopup(True)
    owner.date_to = QDateEdit(QDate.currentDate())
    owner.date_to.setCalendarPopup(True)
    refresh = QPushButton("Refresh")
    refresh.clicked.connect(on_refresh)
    row = QHBoxLayout()
    row.addWidget(QLabel("Invoice date from"))
    row.addWidget(owner.date_from)
    row.addWidget(QLabel("to"))
    row.addWidget(owner.date_to)
    row.addWidget(refresh)
    return row


class CancelledInvoicesScreen(QWidget):
    COLUMNS = ["Invoice Date", "Invoice No", "Customer", "Taxable", "GST", "Total",
               "Cancelled By", "Cancelled On", "Reason"]

    def __init__(self, sales_service: SalesService | None = None):
        super().__init__()
        self.sales_service = sales_service or SalesService()
        self.rows: list[dict] = []

        controls = _date_controls(self, self.refresh)
        self.excel_button = QPushButton("Export Excel")
        self.excel_button.clicked.connect(lambda: self.on_export("xlsx"))
        self.pdf_button = QPushButton("Export PDF")
        self.pdf_button.clicked.connect(lambda: self.on_export("pdf"))
        controls.addStretch(1)
        controls.addWidget(self.excel_button)
        controls.addWidget(self.pdf_button)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary = QLabel("")

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.table)
        layout.addWidget(self.summary)
        self.refresh()

    def _range(self):
        return self.date_from.date().toPython(), self.date_to.date().toPython()

    def refresh(self):
        try:
            self.rows = self.sales_service.list_cancelled_invoices(*self._range())
        except Exception:
            logger.exception("Failed to load cancelled invoices")
            QMessageBox.critical(self, "Error", "Could not load cancelled invoices.")
            return
        self.table.setRowCount(len(self.rows))
        for row, r in enumerate(self.rows):
            gst = r["cgst"] + r["sgst"] + r["igst"]
            values = [
                r["date"].strftime("%d-%m-%Y"), r["invoice_no"], r["customer_name"],
                f"{r['taxable_amount']:,.2f}", f"{gst:,.2f}", f"{r['total']:,.2f}",
                r["cancelled_by"] or "",
                r["cancelled_date"].strftime("%d-%m-%Y %H:%M") if r["cancelled_date"] else "",
                r["cancellation_reason"] or "",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        total = sum(r["total"] for r in self.rows)
        self.summary.setText(
            f"{len(self.rows)} cancelled invoice(s), total {total:,.2f} — excluded from every "
            "sales and GST figure. Cancelled-on times are UTC."
        )

    def on_export(self, kind: str):
        date_from, date_to = self._range()
        default = f"cancelled_invoices_{date_from}_{date_to}.{kind}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export cancelled invoices", default,
            "Excel Files (*.xlsx)" if kind == "xlsx" else "PDF Files (*.pdf)",
        )
        if not path:
            return
        title = (f"Cancelled Invoices — invoice dates {date_from:%d-%m-%Y} to "
                 f"{date_to:%d-%m-%Y}")
        try:
            (export_excel if kind == "xlsx" else export_pdf)(self.rows, path, title)
        except Exception as exc:
            logger.exception("Failed to export cancelled invoices")
            QMessageBox.critical(self, "Error", f"Could not export:\n{exc}")
            return
        QMessageBox.information(self, "Exported", f"Saved to:\n{path}")


class SequenceCheckScreen(QWidget):
    COLUMNS = ["Series", "First", "Last", "Invoices", "Missing", "Missing number(s)"]

    def __init__(self, sales_service: SalesService | None = None):
        super().__init__()
        self.sales_service = sales_service or SalesService()
        self.result: dict | None = None

        controls = _date_controls(self, self.refresh)
        self.excel_button = QPushButton("Export Excel")
        self.excel_button.clicked.connect(self.on_export)
        controls.addStretch(1)
        controls.addWidget(self.excel_button)

        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(QLabel(
            "Checks every invoice number series for missing numbers. Cancelled invoices count "
            "as present — they stay in the sequence — so this should be empty."
        ))
        layout.addWidget(self.verdict)
        layout.addWidget(self.table)
        self.refresh()

    def refresh(self):
        date_from, date_to = self.date_from.date().toPython(), self.date_to.date().toPython()
        try:
            self.result = self.sales_service.check_invoice_sequence(date_from, date_to)
        except Exception:
            logger.exception("Failed to check the invoice sequence")
            QMessageBox.critical(self, "Error", "Could not check the invoice sequence.")
            return
        gaps = {g["series"]: g for g in self.result["gaps"]}
        series = self.result["series"]
        self.table.setRowCount(len(series))
        for row, s in enumerate(series):
            missing = gaps.get(s["series"], {}).get("missing", [])
            values = [s["series"], s["first"], s["last"], str(s["count"]),
                      str(s["missing_count"]), ", ".join(missing)]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

        missing_total = sum(g["count"] for g in self.result["gaps"])
        note = ""
        if self.result["unchecked"]:
            note = (f" {len(self.result['unchecked'])} number(s) contain no digits and could not "
                    "be checked.")
        if not series:
            self.verdict.setText("No invoices in this date range." + note)
            self.verdict.setStyleSheet("")
        elif missing_total:
            self.verdict.setText(f"⚠ {missing_total} number(s) missing from the series." + note)
            self.verdict.setStyleSheet("color: #b00020; font-weight: bold;")
        else:
            self.verdict.setText("✓ No gaps — every series is consecutive." + note)
            self.verdict.setStyleSheet("color: #1b7a1b; font-weight: bold;")

    def on_export(self):
        if self.result is None:
            return
        date_from, date_to = self.date_from.date().toPython(), self.date_to.date().toPython()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export sequence check", f"invoice_sequence_{date_from}_{date_to}.xlsx",
            "Excel Files (*.xlsx)",
        )
        if not path:
            return
        title = f"Invoice Sequence Check — {date_from:%d-%m-%Y} to {date_to:%d-%m-%Y}"
        try:
            export_sequence_excel(self.result, path, title)
        except Exception as exc:
            logger.exception("Failed to export the sequence check")
            QMessageBox.critical(self, "Error", f"Could not export:\n{exc}")
            return
        QMessageBox.information(self, "Exported", f"Saved to:\n{path}")
