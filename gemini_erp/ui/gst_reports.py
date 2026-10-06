"""GST registers + HSN summary screen (Milestone 18).

UI only: picks a date range and a view, asks GstReportService for the rows,
shows them, and exports the current view to Excel via OpenPyXL. No figures
are computed here.

Patch v1.2.0: the Sales Register (and its Excel export) carries a separate
"CANCELLED INVOICES" section under the active rows. Those rows are listed for
a complete document trail and are NOT added to the totals.
"""

import logging

from PySide6.QtCore import QDate
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
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

from services.gst_report_service import GstReportService

logger = logging.getLogger(__name__)

# Each view: (label, list of (header, row-key), fetch(date_from, date_to) -> rows)
_NUMERIC_KEYS = {"taxable_amount", "cgst", "sgst", "igst", "total", "quantity", "gst_rate"}


class GstReportsScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._views = self._build_views()
        self._build_ui()
        self.refresh()

    def _build_views(self):
        return {
            "Sales Register": {
                "columns": [
                    ("Date", "date"), ("Invoice No", "invoice_no"),
                    ("Customer", "customer_name"), ("GSTIN", "customer_gstin"),
                    ("HSN", "hsn_code"), ("Taxable", "taxable_amount"),
                    ("CGST", "cgst"), ("SGST", "sgst"), ("IGST", "igst"),
                    ("Total", "total"),
                ],
                "fetch": lambda f, t: GstReportService.get_sales_register(f, t),
                # Listed under the totals, never added to them.
                "cancelled": lambda f, t: GstReportService.get_cancelled_sales_register(f, t),
            },
            "Purchase Register": {
                "columns": [
                    ("Date", "date"), ("Invoice No", "invoice_no"),
                    ("Supplier", "supplier_name"), ("GSTIN", "supplier_gstin"),
                    ("HSN", "hsn_code"), ("Taxable", "taxable_amount"),
                    ("CGST", "cgst"), ("SGST", "sgst"), ("IGST", "igst"),
                    ("Total", "total"),
                ],
                "fetch": lambda f, t: GstReportService.get_purchase_register(f, t),
            },
            "HSN Summary (Sales)": {
                "columns": [
                    ("HSN", "hsn_code"), ("GST Rate %", "gst_rate"),
                    ("Quantity", "quantity"), ("Taxable", "taxable_amount"),
                    ("CGST", "cgst"), ("SGST", "sgst"), ("IGST", "igst"),
                    ("Total", "total"),
                ],
                "fetch": lambda f, t: GstReportService.get_hsn_summary(f, t, "SALES"),
            },
            "HSN Summary (Purchase)": {
                "columns": [
                    ("HSN", "hsn_code"), ("GST Rate %", "gst_rate"),
                    ("Quantity", "quantity"), ("Taxable", "taxable_amount"),
                    ("CGST", "cgst"), ("SGST", "sgst"), ("IGST", "igst"),
                    ("Total", "total"),
                ],
                "fetch": lambda f, t: GstReportService.get_hsn_summary(f, t, "PURCHASE"),
            },
        }

    def _build_ui(self):
        today = QDate.currentDate()
        self.date_from = QDateEdit(today.addDays(-(today.day() - 1)))  # 1st of month
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(today)
        self.date_to.setCalendarPopup(True)

        self.view_combo = QComboBox()
        self.view_combo.addItems(list(self._views.keys()))
        self.view_combo.currentTextChanged.connect(self.refresh)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button = QPushButton("Export to Excel")
        self.export_button.clicked.connect(self.export_to_excel)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("View"))
        controls.addWidget(self.view_combo)
        controls.addWidget(QLabel("From"))
        controls.addWidget(self.date_from)
        controls.addWidget(QLabel("To"))
        controls.addWidget(self.date_to)
        controls.addWidget(self.refresh_button)
        controls.addWidget(self.export_button)
        controls.addStretch()

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        self.totals_label = QLabel("")

        layout = QVBoxLayout()
        layout.addLayout(controls)
        layout.addWidget(self.table)
        layout.addWidget(self.totals_label)
        self.setLayout(layout)

    def _current_view(self):
        return self._views[self.view_combo.currentText()]

    @staticmethod
    def _format(key, value):
        if value is None:
            return ""
        if key in _NUMERIC_KEYS:
            return f"{value:,.2f}"
        return str(value)

    def refresh(self):
        view = self._current_view()
        date_from = self.date_from.date().toPython()
        date_to = self.date_to.date().toPython()
        try:
            rows = view["fetch"](date_from, date_to)
            cancelled = view["cancelled"](date_from, date_to) if "cancelled" in view else []
        except Exception:
            logger.exception("Failed to load GST report")
            QMessageBox.critical(self, "Error", "Could not load the GST report.")
            return

        # The cancelled-section heading spans the row; drop it on every redraw
        # so it never bleeds into another view.
        self.table.clearSpans()
        columns = view["columns"]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([h for h, _ in columns])
        # Active rows, then (if any) a heading row and the cancelled rows.
        self.table.setRowCount(len(rows) + (len(cancelled) + 1 if cancelled else 0))

        totals = {"taxable_amount": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "total": 0.0}
        for r_idx, row in enumerate(rows):
            for c_idx, (_, key) in enumerate(columns):
                self.table.setItem(r_idx, c_idx, QTableWidgetItem(self._format(key, row.get(key))))
            for key in totals:
                if key in row:
                    totals[key] += row[key]

        if cancelled:
            heading_row = len(rows)
            heading = QTableWidgetItem("CANCELLED INVOICES — not included in the totals")
            bold = QFont()
            bold.setBold(True)
            heading.setFont(bold)
            heading.setForeground(QBrush(QColor("#b00020")))
            self.table.setItem(heading_row, 0, heading)
            self.table.setSpan(heading_row, 0, 1, len(columns))
            grey, struck = QBrush(QColor("#888888")), QFont()
            struck.setStrikeOut(True)
            for offset, row in enumerate(cancelled, start=1):
                for c_idx, (_, key) in enumerate(columns):
                    item = QTableWidgetItem(self._format(key, row.get(key)))
                    item.setForeground(grey)
                    item.setFont(struck)
                    self.table.setItem(heading_row + offset, c_idx, item)

        self.table.resizeColumnsToContents()
        self.totals_label.setText(
            f"Rows: {len(rows)}   |   Taxable: {totals['taxable_amount']:,.2f}   "
            f"CGST: {totals['cgst']:,.2f}   SGST: {totals['sgst']:,.2f}   "
            f"IGST: {totals['igst']:,.2f}   Total: {totals['total']:,.2f}"
            + (f"   |   {len(cancelled)} cancelled invoice(s) listed, excluded" if cancelled else "")
        )

    def export_to_excel(self):
        view = self._current_view()
        date_from = self.date_from.date().toPython()
        date_to = self.date_to.date().toPython()
        try:
            rows = view["fetch"](date_from, date_to)
            cancelled = view["cancelled"](date_from, date_to) if "cancelled" in view else []
        except Exception:
            logger.exception("Failed to load GST report for export")
            QMessageBox.critical(self, "Error", "Could not load data to export.")
            return

        default_name = f"{self.view_combo.currentText().replace(' ', '_')}_{date_from}_{date_to}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "Export to Excel", default_name, "Excel Files (*.xlsx)")
        if not path:
            return

        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font

            columns = view["columns"]
            wb = Workbook()
            ws = wb.active
            ws.title = self.view_combo.currentText()[:31]
            ws.append([h for h, _ in columns])
            for row in rows:
                ws.append([
                    row.get(key) if key in _NUMERIC_KEYS else self._format(key, row.get(key))
                    for _, key in columns
                ])
            if cancelled:
                ws.append([])
                ws.append(["CANCELLED INVOICES — not included in the totals above"])
                ws.cell(ws.max_row, 1).font = Font(bold=True)
                ws.append([h for h, _ in columns] + ["Cancelled On", "Reason"])
                for row in cancelled:
                    ws.append([
                        row.get(key) if key in _NUMERIC_KEYS else self._format(key, row.get(key))
                        for _, key in columns
                    ] + [self._format("cancelled_date", row.get("cancelled_date")),
                         row.get("cancellation_reason") or ""])
            wb.save(path)
        except Exception:
            logger.exception("Failed to export GST report to Excel")
            QMessageBox.critical(self, "Error", "Could not write the Excel file.")
            return

        QMessageBox.information(self, "Exported", f"Saved {len(rows)} rows to:\n{path}")
