"""Purchase log screen: list past purchase invoices and view one in detail.

UI only collects input and displays results - all data comes from
PurchaseService. Mirrors ui/sales_log.py.
"""

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.purchase_service import PurchaseService


class PurchaseInvoiceDetailDialog(QDialog):
    LINE_COLUMNS = ["Item Code", "Item Name", "Qty", "Rate", "Amount", "GST"]

    def __init__(self, invoice_id: int, purchase_service: PurchaseService, parent=None):
        super().__init__(parent)
        self.invoice_id = invoice_id
        self.purchase_service = purchase_service

        self.setWindowTitle("Purchase Invoice Details")
        self._build_ui()

    def _build_ui(self):
        details = self.purchase_service.get_purchase_invoice_details(self.invoice_id)

        header_form = QFormLayout()
        header_form.addRow("Invoice No:", QLabel(details["invoice_no"]))
        header_form.addRow("Date:", QLabel(details["date"].strftime("%d-%m-%Y")))
        header_form.addRow("Supplier:", QLabel(details["supplier_name"]))
        header_form.addRow("GSTIN:", QLabel(details["supplier_gstin"] or "-"))
        header_form.addRow("State:", QLabel(details["supplier_state"] or "-"))

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

        layout = QVBoxLayout()
        layout.addLayout(header_form)
        layout.addWidget(lines_table)
        layout.addLayout(totals_form)
        self.setLayout(layout)


class PurchaseLogScreen(QWidget):
    COLUMNS = ["Invoice No", "Date", "Supplier", "Taxable", "CGST", "SGST", "IGST", "Total"]

    def __init__(self, purchase_service: PurchaseService | None = None):
        super().__init__()
        self.purchase_service = purchase_service or PurchaseService()
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
        invoices = self.purchase_service.list_purchase_invoices()
        self.invoice_ids = [inv["id"] for inv in invoices]

        self.table.setRowCount(len(invoices))
        for row, inv in enumerate(invoices):
            values = [
                inv["invoice_no"],
                inv["date"].strftime("%d-%m-%Y"),
                inv["supplier_name"],
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
        dialog = PurchaseInvoiceDetailDialog(invoice_id, self.purchase_service, parent=self)
        dialog.exec()
