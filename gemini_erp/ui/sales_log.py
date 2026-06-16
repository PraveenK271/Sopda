"""Sales log screen: list past invoices and view one in detail.

UI only collects input and displays results - all data comes from
SalesService.
"""

import logging

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reports.invoice_pdf import generate_invoice_pdf
from services.sales_service import SalesService

logger = logging.getLogger(__name__)


class InvoiceDetailDialog(QDialog):
    LINE_COLUMNS = ["Item Code", "Item Name", "Qty", "Rate", "Amount", "GST"]

    def __init__(self, invoice_id: int, sales_service: SalesService, parent=None):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.sales_service = sales_service
        self.invoice_no: str | None = None

        self.setWindowTitle("Invoice Details")
        self._build_ui()

    def _build_ui(self):
        details = self.sales_service.get_invoice_details(self.invoice_id)
        self.invoice_no = details["invoice_no"]

        header_form = QFormLayout()
        header_form.addRow("Invoice No:", QLabel(details["invoice_no"]))
        header_form.addRow("Date:", QLabel(details["date"].strftime("%d-%m-%Y")))
        header_form.addRow("Customer:", QLabel(details["customer_name"]))
        header_form.addRow("GSTIN:", QLabel(details["customer_gstin"] or "-"))
        header_form.addRow("State:", QLabel(details["customer_state"] or "-"))

        lines_table = QTableWidget()
        lines_table.setColumnCount(len(self.LINE_COLUMNS))
        lines_table.setHorizontalHeaderLabels(self.LINE_COLUMNS)
        lines_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lines_table.setRowCount(len(details["lines"]))
        for row, line in enumerate(details["lines"]):
            values = [
                line["item_code"], line["item_name"], line["quantity"],
                line["rate"], line["amount"], line["gst_amount"],
            ]
            for col, value in enumerate(values):
                lines_table.setItem(row, col, QTableWidgetItem(str(value)))

        totals_form = QFormLayout()
        totals_form.addRow("Taxable Amount:", QLabel(f"{details['taxable_amount']:.2f}"))
        totals_form.addRow("CGST:", QLabel(f"{details['cgst']:.2f}"))
        totals_form.addRow("SGST:", QLabel(f"{details['sgst']:.2f}"))
        totals_form.addRow("IGST:", QLabel(f"{details['igst']:.2f}"))
        totals_form.addRow("Total:", QLabel(f"{details['total']:.2f}"))

        self.pdf_button = QPushButton("Print / Save PDF")
        self.pdf_button.clicked.connect(self.on_save_pdf)

        layout = QVBoxLayout()
        layout.addLayout(header_form)
        layout.addWidget(lines_table)
        layout.addLayout(totals_form)
        layout.addWidget(self.pdf_button)
        self.setLayout(layout)

    def on_save_pdf(self):
        default_name = f"{self.invoice_no}.pdf".replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Invoice PDF", default_name, "PDF Files (*.pdf)"
        )
        if not path:
            return

        try:
            generate_invoice_pdf(self.invoice_id, path)
        except Exception as exc:
            logger.exception("Failed to generate invoice PDF")
            QMessageBox.critical(self, "Error", f"Could not generate PDF:\n{exc}")
            return

        QMessageBox.information(self, "Saved", f"Invoice PDF saved to:\n{path}")


class SalesLogScreen(QWidget):
    COLUMNS = ["Invoice No", "Date", "Customer", "Taxable", "CGST", "SGST", "IGST", "Total"]

    def __init__(self, sales_service: SalesService | None = None):
        super().__init__()
        self.sales_service = sales_service or SalesService()
        self.invoice_ids: list[int] = []

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        self.setLayout(layout)

        self.refresh_invoices()

    def refresh_invoices(self):
        invoices = self.sales_service.list_invoices()
        self.invoice_ids = [inv["id"] for inv in invoices]

        self.table.setRowCount(len(invoices))
        for row, inv in enumerate(invoices):
            values = [
                inv["invoice_no"],
                inv["date"].strftime("%d-%m-%Y"),
                inv["customer_name"],
                f"{inv['taxable_amount']:.2f}",
                f"{inv['cgst']:.2f}",
                f"{inv['sgst']:.2f}",
                f"{inv['igst']:.2f}",
                f"{inv['total']:.2f}",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))

    def on_row_double_clicked(self, row: int, _column: int):
        invoice_id = self.invoice_ids[row]
        dialog = InvoiceDetailDialog(invoice_id, self.sales_service, parent=self)
        dialog.exec()
