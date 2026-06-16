"""GST registers + HSN summary screen (Milestone 18).

UI only: picks a date range and a view, asks GstReportService for the rows,
shows them, and exports the current view to Excel via OpenPyXL. No figures
are computed here.
"""

import logging

from PySide6.QtCore import QDate
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
        except Exception:
            logger.exception("Failed to load GST report")
            QMessageBox.critical(self, "Error", "Could not load the GST report.")
            return

        columns = view["columns"]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([h for h, _ in columns])
        self.table.setRowCount(len(rows))

        totals = {"taxable_amount": 0.0, "cgst": 0.0, "sgst": 0.0, "igst": 0.0, "total": 0.0}
        for r_idx, row in enumerate(rows):
            for c_idx, (_, key) in enumerate(columns):
                self.table.setItem(r_idx, c_idx, QTableWidgetItem(self._format(key, row.get(key))))
            for key in totals:
                if key in row:
                    totals[key] += row[key]

        self.table.resizeColumnsToContents()
        self.totals_label.setText(
            f"Rows: {len(rows)}   |   Taxable: {totals['taxable_amount']:,.2f}   "
            f"CGST: {totals['cgst']:,.2f}   SGST: {totals['sgst']:,.2f}   "
            f"IGST: {totals['igst']:,.2f}   Total: {totals['total']:,.2f}"
        )

    def export_to_excel(self):
        view = self._current_view()
        date_from = self.date_from.date().toPython()
        date_to = self.date_to.date().toPython()
        try:
            rows = view["fetch"](date_from, date_to)
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
            wb.save(path)
        except Exception:
            logger.exception("Failed to export GST report to Excel")
            QMessageBox.critical(self, "Error", "Could not write the Excel file.")
            return

        QMessageBox.information(self, "Exported", f"Saved {len(rows)} rows to:\n{path}")
