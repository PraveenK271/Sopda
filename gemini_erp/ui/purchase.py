"""Purchase screen: pick a supplier and items, see totals, save the
purchase invoice.

UI only collects input and displays results - saving, stock addition and
GST calculation all live in the service layer. Mirrors ui/billing.py.
"""

import logging
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
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

from services.gst_service import split_gst
from services.item_service import ItemService
from services.purchase_service import PurchaseService
from services.supplier_service import SupplierService

logger = logging.getLogger(__name__)


class AddItemDialog(QDialog):
    """Small dialog to add a new item without leaving the Purchase screen.

    Saving calls ItemService.add_item() - the same service the Items page
    uses - so both enforce the same validation (e.g. duplicate item codes).
    """

    def __init__(self, item_service: ItemService, parent=None):
        super().__init__(parent)
        self.item_service = item_service
        self.new_item: dict | None = None

        self.setWindowTitle("Add New Item")

        self.code_input = QLineEdit()
        self.name_input = QLineEdit()
        self.hsn_input = QLineEdit()
        self.gst_input = QLineEdit()
        self.unit_input = QLineEdit()
        self.reorder_level_input = QLineEdit()

        form = QFormLayout()
        form.addRow("Code", self.code_input)
        form.addRow("Name", self.name_input)
        form.addRow("HSN Code", self.hsn_input)
        form.addRow("GST Rate (%)", self.gst_input)
        form.addRow("Unit", self.unit_input)
        form.addRow("Reorder Level", self.reorder_level_input)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.on_save)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.save_button)
        buttons_layout.addWidget(self.cancel_button)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(buttons_layout)
        self.setLayout(layout)

    def on_save(self):
        code = self.code_input.text().strip()
        name = self.name_input.text().strip()
        if not code or not name:
            QMessageBox.warning(self, "Missing data", "Code and Name are required.")
            return

        try:
            item = self.item_service.add_item(
                code=code,
                name=name,
                hsn_code=self.hsn_input.text().strip() or None,
                gst_rate=self._to_float(self.gst_input.text()),
                unit=self.unit_input.text().strip() or None,
                opening_stock=0,
                reorder_level=self._to_float(self.reorder_level_input.text()),
            )
        except Exception as exc:
            logger.exception("Failed to add item")
            QMessageBox.critical(self, "Error", f"Could not add item:\n{exc}")
            return

        self.new_item = {
            "id": item.id,
            "code": item.code,
            "name": item.name,
            "hsn_code": item.hsn_code,
            "gst_rate": float(item.gst_rate),
            "unit": item.unit,
            "opening_stock": float(item.opening_stock),
            "reorder_level": float(item.reorder_level),
        }
        self.accept()

    @staticmethod
    def _to_float(text: str) -> float:
        text = text.strip()
        return float(text) if text else 0.0


class PurchaseScreen(QWidget):
    LINE_COLUMNS = ["Item", "Qty", "Rate", "Amount", "GST"]

    def __init__(
        self,
        item_service: ItemService | None = None,
        supplier_service: SupplierService | None = None,
        purchase_service: PurchaseService | None = None,
    ):
        super().__init__()
        self.item_service = item_service or ItemService()
        self.supplier_service = supplier_service or SupplierService()
        self.purchase_service = purchase_service or PurchaseService()

        self.lines: list[dict] = []

        self._build_ui()
        self.refresh_lookups()

    def _build_ui(self):
        self.invoice_no_input = QLineEdit()
        self.date_input = QDateEdit()
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.supplier_combo = QComboBox()
        self.supplier_combo.currentIndexChanged.connect(self.refresh_lines_table)

        header_form = QFormLayout()
        header_form.addRow("Supplier Invoice No", self.invoice_no_input)
        header_form.addRow("Date", self.date_input)
        header_form.addRow("Supplier", self.supplier_combo)

        # Quick "add a new supplier" so purchase entry can be tested without a
        # separate Supplier Master screen.
        self.new_supplier_name = QLineEdit()
        self.new_supplier_gstin = QLineEdit()
        self.new_supplier_address = QLineEdit()
        self.new_supplier_state = QLineEdit()
        self.add_supplier_button = QPushButton("Add Supplier")
        self.add_supplier_button.clicked.connect(self.on_add_supplier)

        new_supplier_form = QFormLayout()
        new_supplier_form.addRow("Name", self.new_supplier_name)
        new_supplier_form.addRow("GSTIN", self.new_supplier_gstin)
        new_supplier_form.addRow("Address", self.new_supplier_address)
        new_supplier_form.addRow("State", self.new_supplier_state)
        new_supplier_box = QGroupBox("New Supplier")
        new_supplier_layout = QVBoxLayout()
        new_supplier_layout.addLayout(new_supplier_form)
        new_supplier_layout.addWidget(self.add_supplier_button)
        new_supplier_box.setLayout(new_supplier_layout)

        # Line entry
        self.item_combo = QComboBox()
        self.new_item_button = QPushButton("+ New Item")
        self.new_item_button.clicked.connect(self.on_new_item)
        self.qty_input = QLineEdit()
        self.rate_input = QLineEdit()
        self.add_line_button = QPushButton("Add Line")
        self.add_line_button.clicked.connect(self.on_add_line)

        line_form = QHBoxLayout()
        line_form.addWidget(QLabel("Item"))
        line_form.addWidget(self.item_combo)
        line_form.addWidget(self.new_item_button)
        line_form.addWidget(QLabel("Qty"))
        line_form.addWidget(self.qty_input)
        line_form.addWidget(QLabel("Rate"))
        line_form.addWidget(self.rate_input)
        line_form.addWidget(self.add_line_button)

        self.lines_table = QTableWidget()
        self.lines_table.setColumnCount(len(self.LINE_COLUMNS))
        self.lines_table.setHorizontalHeaderLabels(self.LINE_COLUMNS)
        self.lines_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

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

        self.save_button = QPushButton("Save Purchase")
        self.save_button.clicked.connect(self.on_save_purchase)

        layout = QVBoxLayout()
        layout.addLayout(header_form)
        layout.addWidget(new_supplier_box)
        layout.addLayout(line_form)
        layout.addWidget(self.lines_table)
        layout.addLayout(totals_layout)
        layout.addWidget(self.save_button)
        self.setLayout(layout)

    def refresh_lookups(self):
        self.item_combo.clear()
        for item in self.item_service.list_items():
            self.item_combo.addItem(f"{item['code']} - {item['name']}", item)

        current_supplier_id = None
        current_data = self.supplier_combo.currentData()
        if current_data:
            current_supplier_id = current_data["id"]

        self.supplier_combo.clear()
        for supplier in self.supplier_service.list_suppliers():
            self.supplier_combo.addItem(f"{supplier['name']} ({supplier['state']})", supplier)
            if supplier["id"] == current_supplier_id:
                self.supplier_combo.setCurrentIndex(self.supplier_combo.count() - 1)

    def on_add_supplier(self):
        name = self.new_supplier_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing data", "Supplier name is required.")
            return

        try:
            self.supplier_service.add_supplier(
                name=name,
                gstin=self.new_supplier_gstin.text().strip() or None,
                address=self.new_supplier_address.text().strip() or None,
                state=self.new_supplier_state.text().strip() or None,
            )
        except Exception as exc:
            logger.exception("Failed to add supplier")
            QMessageBox.critical(self, "Error", f"Could not add supplier:\n{exc}")
            return

        for field in (
            self.new_supplier_name, self.new_supplier_gstin,
            self.new_supplier_address, self.new_supplier_state,
        ):
            field.clear()
        self.refresh_lookups()

    def on_new_item(self):
        dialog = AddItemDialog(self.item_service, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.new_item is None:
            return

        self.refresh_lookups()
        new_item_id = dialog.new_item["id"]
        for index in range(self.item_combo.count()):
            data = self.item_combo.itemData(index)
            if data and data["id"] == new_item_id:
                self.item_combo.setCurrentIndex(index)
                break

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

        self.lines.append({
            "item_id": item_data["id"],
            "code": item_data["code"],
            "name": item_data["name"],
            "gst_rate": item_data["gst_rate"],
            "quantity": quantity,
            "rate": rate,
        })
        self.qty_input.clear()
        self.rate_input.clear()
        self.refresh_lines_table()

    def refresh_lines_table(self):
        supplier_data = self.supplier_combo.currentData()
        supplier_state = supplier_data["state"] if supplier_data else None

        self.lines_table.setRowCount(len(self.lines))
        total_taxable = total_cgst = total_sgst = total_igst = Decimal("0")

        for row, line in enumerate(self.lines):
            amount = (line["quantity"] * line["rate"]).quantize(Decimal("0.01"))
            cgst, sgst, igst = split_gst(amount, line["gst_rate"], supplier_state)
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

    def on_save_purchase(self):
        invoice_no = self.invoice_no_input.text().strip()
        supplier_data = self.supplier_combo.currentData()

        if not invoice_no:
            QMessageBox.warning(self, "Missing data", "Supplier invoice number is required.")
            return
        if supplier_data is None:
            QMessageBox.warning(self, "Missing data", "Add a supplier first.")
            return
        if not self.lines:
            QMessageBox.warning(self, "Missing data", "Add at least one line item.")
            return

        invoice_date = self.date_input.date().toPython()

        try:
            invoice = self.purchase_service.create_purchase_invoice(
                invoice_no=invoice_no,
                invoice_date=invoice_date,
                supplier_id=supplier_data["id"],
                lines=[
                    {"item_id": line["item_id"], "quantity": line["quantity"], "rate": line["rate"]}
                    for line in self.lines
                ],
            )
        except Exception as exc:
            logger.exception("Failed to save purchase invoice")
            QMessageBox.critical(self, "Error", f"Could not save purchase invoice:\n{exc}")
            return

        QMessageBox.information(self, "Saved", f"Purchase invoice {invoice.invoice_no} saved.")
        self._after_save(invoice)
        self.lines = []
        self.invoice_no_input.clear()
        self.refresh_lines_table()
        self.refresh_lookups()

    def _after_save(self, invoice):
        """Hook called after a successful save. Base does nothing; the OCR
        screen overrides it to link its scanned document to the new invoice."""
