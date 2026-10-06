"""Sales log screen: list past invoices and view one in detail.

UI only collects input and displays results - all data comes from
SalesService.

Patch v1.1.0 (P3): an "Edit" action (Administrator / Accountant only — the
button is not even created for other roles, and the service enforces the same
rule) and an "Edit History" view of every edit: who, when, why.

Patch v1.2.0: cancelled invoices stay listed (greyed, struck through, Status
CANCELLED) with a show/hide filter; "Cancel Invoice" and "Correct Invoice
Number" actions for Administrators only (again enforced in the service).
"""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reports.invoice_pdf import generate_invoice_pdf
from services.sales_service import STATUS_CANCELLED, SalesService
from services.session_context import SessionContext

logger = logging.getLogger(__name__)

ACTION_LABELS = {"EDIT": "Edit", "CANCEL": "Cancelled", "NUMBER_CORRECTION": "Number corrected"}


def _line_summary(snapshot: dict | None) -> str:
    if not snapshot:
        return "-"
    lines = ", ".join(
        f"{l['item_code']} x {float(l['quantity']):g} @ {float(l['rate']):g}" for l in snapshot["lines"]
    )
    return (
        f"{snapshot['invoice_no']} | {snapshot['customer_name']} | {snapshot['date']} | {lines} | "
        f"total {float(snapshot['total']):.2f}"
        + (f" | {snapshot['status']}" if snapshot.get("status") else "")
    )


def save_invoice_pdf(parent, invoice_id: int, invoice_no: str) -> None:
    """Ask where to save, then render the invoice PDF. Shared by the detail
    view and the post-cancel / post-correction prompts."""
    default_name = f"{invoice_no}.pdf".replace("/", "-")
    path, _ = QFileDialog.getSaveFileName(parent, "Save Invoice PDF", default_name, "PDF Files (*.pdf)")
    if not path:
        return
    try:
        generate_invoice_pdf(invoice_id, path)
    except Exception as exc:
        logger.exception("Failed to generate invoice PDF")
        QMessageBox.critical(parent, "Error", f"Could not generate PDF:\n{exc}")
        return
    QMessageBox.information(parent, "Saved", f"Invoice PDF saved to:\n{path}")


class EditHistoryDialog(QDialog):
    """Every change to one invoice: what, who, when, why, and before -> after."""

    COLUMNS = ["#", "Action", "On", "By", "Reason", "Before", "After"]

    def __init__(self, invoice_id: int, sales_service: SalesService, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit History")
        self.resize(1100, 320)

        history = sales_service.get_edit_history(invoice_id)
        table = QTableWidget()
        table.setColumnCount(len(self.COLUMNS))
        table.setHorizontalHeaderLabels(self.COLUMNS)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setRowCount(len(history))
        for row, h in enumerate(history):
            values = [
                str(row + 1),
                ACTION_LABELS.get(h["action"], h["action"]),
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
        layout.addWidget(QLabel("This invoice has not been changed." if not history else
                                f"{len(history)} change(s). Times are UTC."))
        layout.addWidget(table)
        self.setLayout(layout)


class CancelInvoiceDialog(QDialog):
    """Confirm a cancellation: says plainly what happens, and needs the invoice
    number typed back plus a reason before OK is enabled — an irreversible
    action should not be one stray click away."""

    def __init__(self, details: dict, parent=None):
        super().__init__(parent)
        self.invoice_no = details["invoice_no"]
        self.setWindowTitle(f"Cancel Invoice {self.invoice_no}")
        self.setMinimumWidth(520)

        summary = QLabel(
            f"<b>{details['invoice_no']}</b> dated {details['date'].strftime('%d-%m-%Y')} — "
            f"{details['customer_name']} — total {details['total']:,.2f}"
        )
        explanation = QLabel(
            "Cancelling this invoice will:\n"
            "  • put every item on it back into stock,\n"
            "  • reverse its accounting (sales, GST and the customer's balance),\n"
            "  • keep the invoice visible, marked CANCELLED, with its lines readable,\n"
            "  • keep the invoice number USED — it can never be reused.\n\n"
            "This cannot be undone. For a mistyped number, use 'Correct Invoice Number' "
            "instead."
        )
        explanation.setWordWrap(True)

        self.confirm_input = QLineEdit()
        self.confirm_input.setPlaceholderText(f"Type {self.invoice_no} to confirm")
        self.reason_input = QPlainTextEdit()
        self.reason_input.setPlaceholderText("Required: why is this sale being cancelled?")
        self.reason_input.setFixedHeight(70)

        form = QFormLayout()
        form.addRow("Type the invoice number", self.confirm_input)
        form.addRow("Reason", self.reason_input)

        self.buttons = QDialogButtonBox()
        self.ok_button = self.buttons.addButton("Cancel Invoice", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton("Keep Invoice", QDialogButtonBox.ButtonRole.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.ok_button.setEnabled(False)
        self.confirm_input.textChanged.connect(self._update_ok)
        self.reason_input.textChanged.connect(self._update_ok)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

    def reason(self) -> str:
        return self.reason_input.toPlainText().strip()

    def _update_ok(self):
        self.ok_button.setEnabled(
            self.confirm_input.text().strip() == self.invoice_no and bool(self.reason())
        )


class CorrectNumberDialog(QDialog):
    """Correct a mistyped invoice number: old number read-only, new number,
    mandatory reason. Changes the label only."""

    def __init__(self, details: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Correct Invoice Number")
        self.setMinimumWidth(480)

        self.old_input = QLineEdit(details["invoice_no"])
        self.old_input.setReadOnly(True)
        self.new_input = QLineEdit()
        self.new_input.setPlaceholderText("The number as it is in the bill book")
        self.new_input.setMaxLength(16)
        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("Required: e.g. typing mistake")

        explanation = QLabel(
            "This changes ONLY the invoice number. Stock and accounts are untouched; the "
            "accounting narrations are updated so the Day Book and ledgers show the "
            "corrected number. The change is recorded in the invoice's Edit History."
        )
        explanation.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Current number", self.old_input)
        form.addRow("Correct number", self.new_input)
        form.addRow("Reason", self.reason_input)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setEnabled(False)
        self.new_input.textChanged.connect(self._update_ok)
        self.reason_input.textChanged.connect(self._update_ok)

        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _update_ok(self):
        self.ok_button.setEnabled(
            bool(self.new_input.text().strip()) and bool(self.reason_input.text().strip())
        )


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
        if details["status"] == STATUS_CANCELLED:
            banner = QLabel(
                f"CANCELLED on {details['cancelled_date']:%d-%m-%Y} by "
                f"{details['cancelled_by'] or '-'}: {details['cancellation_reason'] or ''}"
            )
            banner.setStyleSheet("color: #b00020; font-weight: bold;")
            banner.setWordWrap(True)
            header_form.addRow(banner)
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
        save_invoice_pdf(self, self.invoice_id, self.invoice_no)


class SalesLogScreen(QWidget):
    COLUMNS = ["Invoice No", "Date", "Customer", "Taxable", "CGST", "SGST", "IGST", "Total",
               "Edits", "Status"]
    STATUS_COLUMN = 9

    # Emitted with the invoice id when the user asks to edit a saved invoice;
    # MainWindow loads it into the Billing screen and switches to that tab.
    edit_requested = Signal(int)
    # Emitted after a cancellation or number correction, so other screens
    # (stock, reports) can refresh.
    invoices_changed = Signal()

    def __init__(self, sales_service: SalesService | None = None):
        super().__init__()
        self.sales_service = sales_service or SalesService()
        self.invoices: list[dict] = []

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)
        self.table.itemSelectionChanged.connect(self._update_buttons)

        user = SessionContext.get_user()
        buttons_layout = QHBoxLayout()
        # A role that may not act never even gets the button (and the service
        # refuses anyway).
        self.edit_button = self.correct_button = self.cancel_button = None
        if SalesService.user_can_edit_invoices(user):
            self.edit_button = QPushButton("Edit Selected Invoice")
            self.edit_button.clicked.connect(self.on_edit_selected)
            buttons_layout.addWidget(self.edit_button)
        if SalesService.user_can_cancel_invoices(user):
            self.correct_button = QPushButton("Correct Invoice Number")
            self.correct_button.clicked.connect(self.on_correct_number)
            buttons_layout.addWidget(self.correct_button)
            self.cancel_button = QPushButton("Cancel Invoice")
            self.cancel_button.clicked.connect(self.on_cancel_selected)
            buttons_layout.addWidget(self.cancel_button)
        self.history_button = QPushButton("Edit History")
        self.history_button.clicked.connect(self.on_history_selected)
        buttons_layout.addWidget(self.history_button)
        buttons_layout.addStretch(1)
        # Shown by default: the user must be able to see that a number exists
        # and is void.
        self.show_cancelled = QCheckBox("Show cancelled invoices")
        self.show_cancelled.setChecked(True)
        self.show_cancelled.toggled.connect(self.refresh_invoices)
        buttons_layout.addWidget(self.show_cancelled)

        layout = QVBoxLayout()
        layout.addLayout(buttons_layout)
        layout.addWidget(self.table)
        layout.addWidget(QLabel("Double-click a row to view details. Cancelled invoices are "
                                "greyed out and excluded from every sales and GST total."))
        self.setLayout(layout)

        self.refresh_invoices()

    @property
    def invoice_ids(self) -> list[int]:
        return [inv["id"] for inv in self.invoices]

    def _selected(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.invoices):
            QMessageBox.warning(self, "No selection", "Select an invoice in the table first.")
            return None
        return self.invoices[row]

    def _update_buttons(self):
        """A cancelled invoice is read-only: no Edit / Correct / Cancel."""
        row = self.table.currentRow()
        active = 0 <= row < len(self.invoices) and self.invoices[row]["status"] != STATUS_CANCELLED
        for button in (self.edit_button, self.correct_button, self.cancel_button):
            if button is not None:
                button.setEnabled(active)

    def on_edit_selected(self):
        invoice = self._selected()
        if invoice is not None:
            self.edit_requested.emit(invoice["id"])

    def on_history_selected(self):
        invoice = self._selected()
        if invoice is not None:
            EditHistoryDialog(invoice["id"], self.sales_service, parent=self).exec()

    def on_cancel_selected(self):
        invoice = self._selected()
        if invoice is None:
            return
        details = self.sales_service.get_invoice_details(invoice["id"])
        dialog = CancelInvoiceDialog(details, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        reason, username = dialog.reason(), SessionContext.get_username()

        try:
            warnings = self.sales_service.preview_cancellation(invoice["id"], reason, username)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot cancel invoice", str(exc))
            return
        if warnings and not self._confirm(warnings, "Cancel the invoice anyway?"):
            return
        try:
            cancelled = self.sales_service.cancel_invoice(invoice["id"], reason, username)
        except Exception as exc:
            logger.exception("Failed to cancel invoice")
            QMessageBox.critical(self, "Error", f"Could not cancel invoice:\n{exc}")
            return

        self.refresh_invoices()
        self.invoices_changed.emit()
        answer = QMessageBox.question(
            self, "Invoice cancelled",
            f"Invoice {cancelled.invoice_no} is cancelled. Its stock is back in inventory and "
            "its accounting is reversed.\n\nAny copy printed before is now out of date. Save "
            "the PDF marked CANCELLED now?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            save_invoice_pdf(self, cancelled.id, cancelled.invoice_no)

    def on_correct_number(self):
        invoice = self._selected()
        if invoice is None:
            return
        details = self.sales_service.get_invoice_details(invoice["id"])
        dialog = CorrectNumberDialog(details, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_no, reason = dialog.new_input.text(), dialog.reason_input.text()
        username = SessionContext.get_username()

        try:
            warnings = self.sales_service.preview_number_correction(invoice["id"], new_no, reason, username)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot correct number", str(exc))
            return
        if warnings and not self._confirm(warnings, "Correct the number anyway?"):
            return
        try:
            corrected = self.sales_service.correct_invoice_number(invoice["id"], new_no, reason, username)
        except Exception as exc:
            logger.exception("Failed to correct invoice number")
            QMessageBox.critical(self, "Error", f"Could not correct the invoice number:\n{exc}")
            return

        self.refresh_invoices()
        self.invoices_changed.emit()
        answer = QMessageBox.question(
            self, "Number corrected",
            f"Invoice {details['invoice_no']} is now {corrected.invoice_no}.\n\nAny PDF "
            "saved before shows the old number. Save the PDF under the corrected number now?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            save_invoice_pdf(self, corrected.id, corrected.invoice_no)

    def _confirm(self, warnings: list[str], question: str) -> bool:
        answer = QMessageBox.question(
            self, "Please confirm", "\n\n".join(f"• {w}" for w in warnings) + f"\n\n{question}"
        )
        return answer == QMessageBox.StandardButton.Yes

    def refresh_invoices(self):
        self.invoices = self.sales_service.list_invoices(
            include_cancelled=self.show_cancelled.isChecked()
        )
        grey = QBrush(QColor("#888888"))
        struck = QFont()
        struck.setStrikeOut(True)

        self.table.setRowCount(len(self.invoices))
        for row, inv in enumerate(self.invoices):
            cancelled = inv["status"] == STATUS_CANCELLED
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
                "CANCELLED" if cancelled else "Active",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if cancelled:
                    item.setForeground(grey)
                    # Amounts struck through: on the list, not in any total.
                    if col != self.STATUS_COLUMN:
                        item.setFont(struck)
                    else:
                        item.setForeground(QBrush(QColor("#b00020")))
                if col == self.STATUS_COLUMN:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)
        self._update_buttons()

    def on_row_double_clicked(self, row: int, _column: int):
        dialog = InvoiceDetailDialog(self.invoices[row]["id"], self.sales_service, parent=self)
        dialog.exec()
