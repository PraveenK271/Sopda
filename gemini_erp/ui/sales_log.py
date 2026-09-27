"""Sales log screen: list past invoices and view one in detail.

UI only collects input and displays results - all data comes from
SalesService.

Patch v1.1.0 (P3): an "Edit" action (Administrator / Accountant only — the
button is not even created for other roles, and the service enforces the same
rule) and an "Edit History" view of every edit: who, when, why.
"""

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
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
from services.session_context import SessionContext

logger = logging.getLogger(__name__)


def _line_summary(snapshot: dict | None) -> str:
    if not snapshot:
        return "-"
    lines = ", ".join(
        f"{l['item_code']} x {float(l['quantity']):g} @ {float(l['rate']):g}" for l in snapshot["lines"]
    )
    return f"{snapshot['customer_name']} | {snapshot['date']} | {lines} | total {float(snapshot['total']):.2f}"


class EditHistoryDialog(QDialog):
    """Every edit of one invoice: who, when, why, and before -> after."""

    COLUMNS = ["#", "Edited On", "Edited By", "Reason", "Before", "After"]

    def __init__(self, invoice_id: int, sales_service: SalesService, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit History")
        self.resize(1000, 320)

        history = sales_service.get_edit_history(invoice_id)
        table = QTableWidget()
        table.setColumnCount(len(self.COLUMNS))
        table.setHorizontalHeaderLabels(self.COLUMNS)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setRowCount(len(history))
        for row, h in enumerate(history):
            values = [
                str(row + 1),
                h["edited_date"].strftime("%d-%m-%Y %H:%M") if h["edited_date"] else "-",
                h["edited_by"] or "-",
                h["reason"],
                _line_summary(h["before"]),
                _line_summary(h["after"]),
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(value))
        table.resizeColumnsToContents()

        layout = QVBoxLayout()
        layout.addWidget(QLabel("This invoice has not been edited." if not history else
                                f"{len(history)} edit(s). Times are UTC."))
        layout.addWidget(table)
        self.setLayout(layout)


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
        if details["edit_count"]:
            header_form.addRow("Edited:", QLabel(f"{details['edit_count']} time(s)"))

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
        self.history_button = QPushButton("Edit History")
        self.history_button.clicked.connect(self.on_edit_history)

        buttons = QHBoxLayout()
        buttons.addWidget(self.pdf_button)
        buttons.addWidget(self.history_button)

        layout = QVBoxLayout()
        layout.addLayout(header_form)
        layout.addWidget(lines_table)
        layout.addLayout(totals_form)
        layout.addLayout(buttons)
        self.setLayout(layout)

    def on_edit_history(self):
        EditHistoryDialog(self.invoice_id, self.sales_service, parent=self).exec()

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
    COLUMNS = ["Invoice No", "Date", "Customer", "Taxable", "CGST", "SGST", "IGST", "Total", "Edits"]

    # Emitted with the invoice id when the user asks to edit a saved invoice;
    # MainWindow loads it into the Billing screen and switches to that tab.
    edit_requested = Signal(int)

    def __init__(self, sales_service: SalesService | None = None):
        super().__init__()
        self.sales_service = sales_service or SalesService()
        self.invoice_ids: list[int] = []

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)

        buttons_layout = QHBoxLayout()
        # A Sales User must not see Edit at all (the service also refuses).
        self.edit_button = None
        if SalesService.user_can_edit_invoices(SessionContext.get_user()):
            self.edit_button = QPushButton("Edit Selected Invoice")
            self.edit_button.clicked.connect(self.on_edit_selected)
            buttons_layout.addWidget(self.edit_button)
        self.history_button = QPushButton("Edit History")
        self.history_button.clicked.connect(self.on_history_selected)
        buttons_layout.addWidget(self.history_button)
        buttons_layout.addStretch(1)

        layout = QVBoxLayout()
        layout.addLayout(buttons_layout)
        layout.addWidget(self.table)
        layout.addWidget(QLabel("Double-click a row to view details."))
        self.setLayout(layout)

        self.refresh_invoices()

    def _selected_invoice_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.invoice_ids):
            QMessageBox.warning(self, "No selection", "Select an invoice in the table first.")
            return None
        return self.invoice_ids[row]

    def on_edit_selected(self):
        invoice_id = self._selected_invoice_id()
        if invoice_id is not None:
            self.edit_requested.emit(invoice_id)

    def on_history_selected(self):
        invoice_id = self._selected_invoice_id()
        if invoice_id is not None:
            EditHistoryDialog(invoice_id, self.sales_service, parent=self).exec()

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
                str(inv["edit_count"]) if inv["edit_count"] else "",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))

    def on_row_double_clicked(self, row: int, _column: int):
        invoice_id = self.invoice_ids[row]
        dialog = InvoiceDetailDialog(invoice_id, self.sales_service, parent=self)
        dialog.exec()
