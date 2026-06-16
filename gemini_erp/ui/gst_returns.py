"""GST Returns screen (Milestone 19): GSTR-1 and GSTR-3B summaries.

Read-only "figures to enter on the GST portal" — no e-filing integration.
All numbers come from GstReportService; this screen only lays them out.
"""

import logging

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
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


def _money(value) -> QTableWidgetItem:
    return QTableWidgetItem(f"{value:,.2f}")


class GstReturnsScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        today = QDate.currentDate()
        self.date_from = QDateEdit(today.addDays(-(today.day() - 1)))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(today)
        self.date_to.setCalendarPopup(True)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("From"))
        controls.addWidget(self.date_from)
        controls.addWidget(QLabel("To"))
        controls.addWidget(self.date_to)
        controls.addWidget(self.refresh_button)
        controls.addStretch()

        # GSTR-1 B2B table
        self.b2b_table = QTableWidget()
        self.b2b_table.setColumnCount(7)
        self.b2b_table.setHorizontalHeaderLabels(
            ["GSTIN", "Invoice No", "Date", "Taxable", "CGST", "SGST", "IGST"]
        )
        self.b2b_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.b2b_table.setAlternatingRowColors(True)
        self.b2c_label = QLabel("")

        # GSTR-3B summary table
        self.gstr3b_table = QTableWidget()
        self.gstr3b_table.setColumnCount(5)
        self.gstr3b_table.setHorizontalHeaderLabels(
            ["Particulars", "Taxable", "CGST", "SGST", "IGST"]
        )
        self.gstr3b_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.gstr3b_table.setAlternatingRowColors(True)

        layout = QVBoxLayout()
        layout.addLayout(controls)
        layout.addWidget(QLabel("<b>GSTR-1 — B2B (registered customers)</b>"))
        layout.addWidget(self.b2b_table)
        layout.addWidget(self.b2c_label)
        layout.addWidget(QLabel("<b>GSTR-3B — Summary</b>"))
        layout.addWidget(self.gstr3b_table)
        self.setLayout(layout)

    def refresh(self):
        date_from = self.date_from.date().toPython()
        date_to = self.date_to.date().toPython()
        try:
            g1 = GstReportService.get_gstr1_summary(date_from, date_to)
            g3 = GstReportService.get_gstr3b_summary(date_from, date_to)
        except Exception:
            logger.exception("Failed to load GST returns")
            QMessageBox.critical(self, "Error", "Could not load GST returns.")
            return

        self._fill_gstr1(g1)
        self._fill_gstr3b(g3)

    def _fill_gstr1(self, g1: dict):
        b2b = g1["b2b"]
        self.b2b_table.setRowCount(len(b2b))
        for row_idx, r in enumerate(b2b):
            self.b2b_table.setItem(row_idx, 0, QTableWidgetItem(r["gstin"]))
            self.b2b_table.setItem(row_idx, 1, QTableWidgetItem(r["invoice_no"]))
            self.b2b_table.setItem(row_idx, 2, QTableWidgetItem(str(r["date"])))
            self.b2b_table.setItem(row_idx, 3, _money(r["taxable_value"]))
            self.b2b_table.setItem(row_idx, 4, _money(r["cgst"]))
            self.b2b_table.setItem(row_idx, 5, _money(r["sgst"]))
            self.b2b_table.setItem(row_idx, 6, _money(r["igst"]))
        self.b2b_table.resizeColumnsToContents()

        b2c = g1["b2c_small"]
        self.b2c_label.setText(
            "<b>B2C Small (unregistered customers):</b>  "
            f"Taxable {b2c['taxable_value']:,.2f}   CGST {b2c['cgst']:,.2f}   "
            f"SGST {b2c['sgst']:,.2f}   IGST {b2c['igst']:,.2f}"
        )

    def _fill_gstr3b(self, g3: dict):
        outward = g3["outward_taxable_supplies"]
        itc = g3["itc_available"]
        net = g3["net_tax_payable"]
        cf = g3["itc_carried_forward"]

        rows = [
            ("3.1(a) Outward taxable supplies", outward["taxable_amount"],
             outward["cgst"], outward["sgst"], outward["igst"]),
            ("4 ITC available (from purchases)", None, itc["cgst"], itc["sgst"], itc["igst"]),
            ("Net tax payable", None, net["cgst"], net["sgst"], net["igst"]),
            ("ITC carried forward", None, cf["cgst"], cf["sgst"], cf["igst"]),
        ]
        self.gstr3b_table.setRowCount(len(rows))
        for row_idx, (label, taxable, cgst, sgst, igst) in enumerate(rows):
            self.gstr3b_table.setItem(row_idx, 0, QTableWidgetItem(label))
            self.gstr3b_table.setItem(row_idx, 1, _money(taxable) if taxable is not None else QTableWidgetItem(""))
            self.gstr3b_table.setItem(row_idx, 2, _money(cgst))
            self.gstr3b_table.setItem(row_idx, 3, _money(sgst))
            self.gstr3b_table.setItem(row_idx, 4, _money(igst))
        self.gstr3b_table.resizeColumnsToContents()
