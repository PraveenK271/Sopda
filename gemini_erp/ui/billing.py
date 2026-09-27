"""Billing screen: pick a customer and items, see totals, save the invoice.

UI only collects input and displays results - saving, stock deduction and
GST calculation all live in the service layer.

Patch v1.1.0 (P3): the same screen edits a saved invoice when opened from the
Sales Log — invoice number locked, a mandatory reason, and the service's
warnings confirmed before anything is written (SalesService.update_invoice).
"""

import logging
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from reports.invoice_pdf import generate_invoice_pdf
from services.customer_service import CustomerService
from services.session_context import SessionContext
from services.gst_service import split_gst
from services.item_service import ItemService
from services.sales_service import SalesService

logger = logging.getLogger(__name__)


class BillingScreen(QWidget):
    LINE_COLUMNS = ["Item", "Qty", "Rate", "Amount", "GST"]

    def __init__(
        self,
        item_service: ItemService | None = None,
        customer_service: CustomerService | None = None,
        sales_service: SalesService | None = None,
    ):
        super().__init__()
        self.item_service = item_service or ItemService()
        self.customer_service = customer_service or CustomerService()
        self.sales_service = sales_service or SalesService()

        self.lines: list[dict] = []
        # None = the entry row adds a new line; an index = editing that line.
        self._editing_line_index: int | None = None
        self.last_invoice_id: int | None = None
        self.last_invoice_no: str | None = None
        # None = creating a new invoice; an id = editing that saved invoice.
        self._editing_invoice_id: int | None = None

        self._build_ui()
        self.refresh_lookups()

    def _build_ui(self):
        self.invoice_no_input = QLineEdit()
        self.date_input = QDateEdit()
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.customer_combo = QComboBox()
        self.customer_combo.currentIndexChanged.connect(self.refresh_lines_table)

        # Only shown while editing a saved invoice; required by the service.
        self.edit_banner = QLabel("")
        self.edit_banner.setStyleSheet("color: #8a6d00; font-weight: bold;")
        self.edit_banner.setVisible(False)
        self.edit_reason_input = QLineEdit()
        self.edit_reason_input.setPlaceholderText("Required: why is this invoice being changed?")
        self.edit_reason_label = QLabel("Reason for edit")

        header_form = QFormLayout()
        header_form.addRow(self.edit_banner)
        header_form.addRow("Invoice No", self.invoice_no_input)
        header_form.addRow("Date", self.date_input)
        header_form.addRow("Customer", self.customer_combo)
        header_form.addRow(self.edit_reason_label, self.edit_reason_input)
        self.edit_reason_label.setVisible(False)
        self.edit_reason_input.setVisible(False)

        # Quick "add a new customer" so billing can be tested without a
        # separate Customer Master screen.
        self.new_customer_name = QLineEdit()
        self.new_customer_gstin = QLineEdit()
        self.new_customer_address = QLineEdit()
        self.new_customer_state = QLineEdit()
        self.add_customer_button = QPushButton("Add Customer")
        self.add_customer_button.clicked.connect(self.on_add_customer)

        new_customer_form = QFormLayout()
        new_customer_form.addRow("Name", self.new_customer_name)
        new_customer_form.addRow("GSTIN", self.new_customer_gstin)
        new_customer_form.addRow("Address", self.new_customer_address)
        new_customer_form.addRow("State", self.new_customer_state)
        new_customer_box = QGroupBox("New Customer")
        new_customer_layout = QVBoxLayout()
        new_customer_layout.addLayout(new_customer_form)
        new_customer_layout.addWidget(self.add_customer_button)
        new_customer_box.setLayout(new_customer_layout)

        # Line entry
        self.item_combo = QComboBox()
        # Wider so the full "code - name" of the item stays readable; it also
        # stretches to absorb spare width (see the addWidget stretch below).
        # Same layout as the Purchases line-entry row.
        self.item_combo.setMinimumWidth(320)
        self.qty_input = QLineEdit()
        self.rate_input = QLineEdit()
        # Numeric fields need little room — keep them compact so the width goes
        # to the item dropdown instead.
        self.qty_input.setFixedWidth(80)
        self.rate_input.setFixedWidth(80)
        # add_line_button doubles as "Update Line" while editing a line.
        self.add_line_button = QPushButton("Add Line")
        self.add_line_button.clicked.connect(self.on_add_line)
        self.edit_line_button = QPushButton("Edit Line")
        self.edit_line_button.clicked.connect(self.on_edit_line)

        line_form = QHBoxLayout()
        line_form.addWidget(QLabel("Item"))
        line_form.addWidget(self.item_combo, 1)  # stretch: take the spare width
        line_form.addWidget(QLabel("Qty"))
        line_form.addWidget(self.qty_input)
        line_form.addWidget(QLabel("Rate"))
        line_form.addWidget(self.rate_input)
        line_form.addWidget(self.add_line_button)
        line_form.addWidget(self.edit_line_button)

        self.lines_table = QTableWidget()
        self.lines_table.setColumnCount(len(self.LINE_COLUMNS))
        self.lines_table.setHorizontalHeaderLabels(self.LINE_COLUMNS)
        self.lines_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.lines_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.lines_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.lines_table.doubleClicked.connect(self.on_edit_line)

        self.taxable_label = QLabel("Taxable: 0.00")
        self.cgst_label = QLabel("CGST: 0.00")
        self.sgst_label = QLabel("SGST: 0.00")
        self.igst_label = QLabel("IGST: 0.00")
        self.total_label = QLabel("Total: 0.00")

        totals_layout = QHBoxLayout()
        for label in (
            self.taxable_label, self.cgst_label, self.sgst_label,
            self.igst_label, self.total_label,
        ):
            totals_layout.addWidget(label)

        self.save_button = QPushButton("Save Invoice")
        self.save_button.clicked.connect(self.on_save_invoice)

        self.pdf_button = QPushButton("Print / Save PDF")
        self.pdf_button.setEnabled(False)
        self.pdf_button.clicked.connect(self.on_save_pdf)

        self.cancel_edit_button = QPushButton("Cancel Edit")
        self.cancel_edit_button.clicked.connect(self.on_cancel_edit)
        self.cancel_edit_button.setVisible(False)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.save_button)
        buttons_layout.addWidget(self.pdf_button)
        buttons_layout.addWidget(self.cancel_edit_button)

        layout = QVBoxLayout()
        layout.addLayout(header_form)
        layout.addWidget(new_customer_box)
        layout.addLayout(line_form)
        layout.addWidget(self.lines_table)
        layout.addLayout(totals_layout)
        layout.addLayout(buttons_layout)
        self.setLayout(layout)

    def refresh_lookups(self):
        self.item_combo.clear()
        for item in self.item_service.list_items():
            self.item_combo.addItem(f"{item['code']} - {item['name']}", item)

        current_customer_id = None
        current_data = self.customer_combo.currentData()
        if current_data:
            current_customer_id = current_data["id"]

        self.customer_combo.clear()
        for customer in self.customer_service.list_customers():
            self.customer_combo.addItem(f"{customer['name']} ({customer['state']})", customer)
            if customer["id"] == current_customer_id:
                self.customer_combo.setCurrentIndex(self.customer_combo.count() - 1)

    def on_add_customer(self):
        name = self.new_customer_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing data", "Customer name is required.")
            return

        try:
            self.customer_service.add_customer(
                name=name,
                gstin=self.new_customer_gstin.text().strip() or None,
                address=self.new_customer_address.text().strip() or None,
                state=self.new_customer_state.text().strip() or None,
                created_by=SessionContext.get_username(),
            )
        except Exception as exc:
            logger.exception("Failed to add customer")
            QMessageBox.critical(self, "Error", f"Could not add customer:\n{exc}")
            return

        for field in (
            self.new_customer_name, self.new_customer_gstin,
            self.new_customer_address, self.new_customer_state,
        ):
            field.clear()
        self.refresh_lookups()

    def on_add_line(self):
        item_data = self.item_combo.currentData()
        if item_data is None:
            QMessageBox.warning(self, "No item", "Add an item in Item Master first.")
            return

        try:
            quantity = Decimal(self.qty_input.text().strip())
            rate_text = self.rate_input.text().strip()
            rate = Decimal(rate_text) if rate_text else Decimal("0")
        except InvalidOperation:
            QMessageBox.warning(self, "Invalid input", "Quantity and rate must be numbers.")
            return

        if quantity <= 0:
            QMessageBox.warning(self, "Invalid input", "Quantity must be greater than zero.")
            return

        line = {
            "item_id": item_data["id"],
            "code": item_data["code"],
            "name": item_data["name"],
            "gst_rate": item_data["gst_rate"],
            "quantity": quantity,
            "rate": rate,
        }
        if self._editing_line_index is None:
            self.lines.append(line)
        else:
            self.lines[self._editing_line_index] = line
        self._reset_line_entry()
        self.refresh_lines_table()

    def on_edit_line(self):
        """Load the selected grid line back into the entry row for editing.

        In-memory only — this changes a line before the invoice is saved; nothing
        is written to the database until Save Invoice.
        """
        row = self.lines_table.currentRow()
        if row < 0 or row >= len(self.lines):
            QMessageBox.warning(self, "No selection", "Select a line in the table first.")
            return

        line = self.lines[row]
        for index in range(self.item_combo.count()):
            data = self.item_combo.itemData(index)
            if data and data["id"] == line["item_id"]:
                self.item_combo.setCurrentIndex(index)
                break
        self.qty_input.setText(str(line["quantity"]))
        self.rate_input.setText(str(line["rate"]))

        self._editing_line_index = row
        self.add_line_button.setText("Update Line")

    def _reset_line_entry(self):
        """Clear the entry row and leave line-edit mode."""
        self._editing_line_index = None
        self.qty_input.clear()
        self.rate_input.clear()
        self.add_line_button.setText("Add Line")

    def refresh_lines_table(self):
        customer_data = self.customer_combo.currentData()
        customer_state = customer_data["state"] if customer_data else None

        self.lines_table.setRowCount(len(self.lines))
        total_taxable = total_cgst = total_sgst = total_igst = Decimal("0")

        for row, line in enumerate(self.lines):
            amount = (line["quantity"] * line["rate"]).quantize(Decimal("0.01"))
            cgst, sgst, igst = split_gst(amount, line["gst_rate"], customer_state)
            gst_amount = cgst + sgst + igst

            values = [
                f"{line['code']} - {line['name']}",
                str(line["quantity"]),
                str(line["rate"]),
                str(amount),
                str(gst_amount),
            ]
            for col, value in enumerate(values):
                self.lines_table.setItem(row, col, QTableWidgetItem(value))

            total_taxable += amount
            total_cgst += cgst
            total_sgst += sgst
            total_igst += igst

        total = total_taxable + total_cgst + total_sgst + total_igst
        self.taxable_label.setText(f"Taxable: {total_taxable}")
        self.cgst_label.setText(f"CGST: {total_cgst}")
        self.sgst_label.setText(f"SGST: {total_sgst}")
        self.igst_label.setText(f"IGST: {total_igst}")
        self.total_label.setText(f"Total: {total}")

    def on_save_invoice(self):
        invoice_no = self.invoice_no_input.text().strip()
        customer_data = self.customer_combo.currentData()

        if not invoice_no:
            QMessageBox.warning(self, "Missing data", "Invoice number is required.")
            return
        if customer_data is None:
            QMessageBox.warning(self, "Missing data", "Add a customer first.")
            return
        if not self.lines:
            QMessageBox.warning(self, "Missing data", "Add at least one line item.")
            return

        invoice_date = self.date_input.date().toPython()

        if self._editing_invoice_id is not None:
            self._save_edited_invoice(invoice_no, invoice_date, customer_data["id"])
            return

        try:
            invoice = self.sales_service.create_invoice(
                invoice_no=invoice_no,
                invoice_date=invoice_date,
                customer_id=customer_data["id"],
                lines=[
                    {"item_id": line["item_id"], "quantity": line["quantity"], "rate": line["rate"]}
                    for line in self.lines
                ],
                created_by=SessionContext.get_username(),
            )
        except Exception as exc:
            logger.exception("Failed to save invoice")
            QMessageBox.critical(self, "Error", f"Could not save invoice:\n{exc}")
            return

        QMessageBox.information(self, "Saved", f"Invoice {invoice.invoice_no} saved.")
        # Oversell is allowed but flagged — warn after saving, never block.
        warnings = getattr(invoice, "stock_warnings", [])
        if warnings:
            QMessageBox.warning(self, "Stock warning", "\n".join(warnings))
        self.last_invoice_id = invoice.id
        self.last_invoice_no = invoice.invoice_no
        self.pdf_button.setEnabled(True)
        self.lines = []
        self._reset_line_entry()
        self.invoice_no_input.clear()
        self.refresh_lines_table()
        self.refresh_lookups()

    # ----- editing a saved invoice (patch v1.1.0, P3) ---------------------

    def load_invoice_for_edit(self, invoice_id: int) -> None:
        """Prefill the screen with a saved invoice and switch to edit mode.

        Called from the Sales Log. The invoice number is read-only — it is the
        legal document number — and saving requires a reason.
        """
        try:
            details = self.sales_service.get_invoice_details(invoice_id)
        except Exception as exc:
            logger.exception("Failed to load invoice %s for edit", invoice_id)
            QMessageBox.critical(self, "Error", f"Could not open invoice:\n{exc}")
            return

        self.refresh_lookups()
        self.invoice_no_input.setText(details["invoice_no"])
        self.invoice_no_input.setReadOnly(True)
        d = details["date"]
        self.date_input.setDate(QDate(d.year, d.month, d.day))
        for index in range(self.customer_combo.count()):
            data = self.customer_combo.itemData(index)
            if data and data["id"] == details["customer_id"]:
                self.customer_combo.setCurrentIndex(index)
                break

        self.lines = [
            {
                "item_id": line["item_id"],
                "code": line["item_code"],
                "name": line["item_name"],
                "gst_rate": line["gst_rate"],
                "quantity": Decimal(str(line["quantity"])),
                "rate": Decimal(str(line["rate"])),
            }
            for line in details["lines"]
        ]

        self._editing_invoice_id = invoice_id
        self.edit_banner.setText(
            f"Editing saved invoice {details['invoice_no']} "
            f"(edited {details['edit_count']} time(s) before). The original stock and "
            "accounting entries are reversed and re-posted on save."
        )
        self.edit_banner.setVisible(True)
        self.edit_reason_input.clear()
        self.edit_reason_label.setVisible(True)
        self.edit_reason_input.setVisible(True)
        self.cancel_edit_button.setVisible(True)
        self.save_button.setText("Update Invoice")
        self._reset_line_entry()
        self.refresh_lines_table()

    def on_cancel_edit(self):
        self._exit_edit_mode()
        self.lines = []
        self._reset_line_entry()
        self.invoice_no_input.clear()
        self.refresh_lines_table()

    def _exit_edit_mode(self) -> None:
        self._editing_invoice_id = None
        self.invoice_no_input.setReadOnly(False)
        self.edit_banner.setVisible(False)
        self.edit_reason_input.clear()
        self.edit_reason_label.setVisible(False)
        self.edit_reason_input.setVisible(False)
        self.cancel_edit_button.setVisible(False)
        self.save_button.setText("Save Invoice")

    def _save_edited_invoice(self, invoice_no: str, invoice_date, customer_id: int) -> None:
        reason = self.edit_reason_input.text().strip()
        if not reason:
            QMessageBox.warning(self, "Reason required", "Enter the reason for this edit.")
            return

        new_data = {
            "invoice_no": invoice_no,
            "date": invoice_date,
            "customer_id": customer_id,
            "lines": [
                {"item_id": line["item_id"], "quantity": line["quantity"], "rate": line["rate"]}
                for line in self.lines
            ],
        }
        username = SessionContext.get_username()

        # 1) all checks, nothing written: blockers raise, warnings come back.
        try:
            warnings = self.sales_service.preview_invoice_edit(
                self._editing_invoice_id, new_data, reason, username
            )
        except Exception as exc:
            QMessageBox.critical(self, "Cannot edit invoice", str(exc))
            return
        if warnings:
            answer = QMessageBox.question(
                self, "Please confirm",
                "\n\n".join(f"• {w}" for w in warnings) + "\n\nSave the edit anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        # 2) the edit itself — one transaction in the service.
        try:
            invoice = self.sales_service.update_invoice(
                self._editing_invoice_id, new_data, reason, username
            )
        except Exception as exc:
            logger.exception("Failed to update invoice")
            QMessageBox.critical(self, "Error", f"Could not update invoice:\n{exc}")
            return

        stock_warnings = getattr(invoice, "stock_warnings", [])
        if stock_warnings:
            QMessageBox.warning(self, "Stock warning", "\n".join(stock_warnings))
        self.last_invoice_id = invoice.id
        self.last_invoice_no = invoice.invoice_no
        self.pdf_button.setEnabled(True)
        self._exit_edit_mode()
        self.lines = []
        self._reset_line_entry()
        self.invoice_no_input.clear()
        self.refresh_lines_table()
        self.refresh_lookups()

        # The PDF is rendered from the saved data, so the updated invoice needs
        # a fresh copy — any earlier PDF of it is now out of date.
        answer = QMessageBox.question(
            self, "Updated",
            f"Invoice {invoice.invoice_no} updated (edit #{invoice.edit_count}).\n\n"
            "Any PDF printed before this edit is out of date. Save the updated PDF now?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.on_save_pdf()

    def on_save_pdf(self):
        if self.last_invoice_id is None:
            QMessageBox.warning(self, "No invoice", "Save an invoice first.")
            return

        default_name = f"{self.last_invoice_no}.pdf".replace("/", "-")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Invoice PDF", default_name, "PDF Files (*.pdf)"
        )
        if not path:
            return

        try:
            generate_invoice_pdf(self.last_invoice_id, path)
        except Exception as exc:
            logger.exception("Failed to generate invoice PDF")
            QMessageBox.critical(self, "Error", f"Could not generate PDF:\n{exc}")
            return

        QMessageBox.information(self, "Saved", f"Invoice PDF saved to:\n{path}")
