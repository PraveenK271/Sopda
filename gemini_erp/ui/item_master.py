"""Item Master screen: add an item and view the item list with current stock.

UI only collects input and displays results - all logic lives in ItemService.
"""

import logging

from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.item_service import ItemService
from services.session_context import SessionContext

logger = logging.getLogger(__name__)


class ItemMasterScreen(QWidget):
    COLUMNS = [
        "ID", "Code", "Name", "HSN Code", "GST %", "Unit",
        "Opening Stock", "Reorder Level", "Current Stock",
    ]

    def __init__(self, item_service: ItemService | None = None):
        super().__init__()
        self.item_service = item_service or ItemService()

        # None = adding a new item; an id = editing that existing item.
        self._editing_item_id: int | None = None
        self._items: list[dict] = []

        self.code_input = QLineEdit()
        self.name_input = QLineEdit()
        self.hsn_input = QLineEdit()
        self.gst_input = QLineEdit()
        self.unit_input = QLineEdit()
        self.opening_stock_input = QLineEdit()
        self.reorder_level_input = QLineEdit()

        form = QFormLayout()
        form.addRow("Code", self.code_input)
        form.addRow("Name", self.name_input)
        form.addRow("HSN Code", self.hsn_input)
        form.addRow("GST Rate (%)", self.gst_input)
        form.addRow("Unit", self.unit_input)
        form.addRow("Opening Stock", self.opening_stock_input)
        form.addRow("Reorder Level", self.reorder_level_input)

        # add_button doubles as the "Update Item" button in edit mode.
        self.add_button = QPushButton("Add Item")
        self.add_button.clicked.connect(self.on_add_item)
        self.edit_button = QPushButton("Edit Selected")
        self.edit_button.clicked.connect(self.on_edit_selected)
        self.cancel_button = QPushButton("Cancel Edit")
        self.cancel_button.clicked.connect(self.on_cancel_edit)
        self.cancel_button.setVisible(False)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.add_button)
        buttons_layout.addWidget(self.edit_button)
        buttons_layout.addWidget(self.cancel_button)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self.on_edit_selected)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(buttons_layout)
        layout.addWidget(self.table)
        self.setLayout(layout)

        self.refresh_items()

    def on_add_item(self):
        """Add a new item, or update the one being edited (edit mode)."""
        code = self.code_input.text().strip()
        name = self.name_input.text().strip()
        if not code or not name:
            QMessageBox.warning(self, "Missing data", "Code and Name are required.")
            return

        fields = dict(
            code=code,
            name=name,
            hsn_code=self.hsn_input.text().strip() or None,
            gst_rate=self._to_float(self.gst_input.text()),
            unit=self.unit_input.text().strip() or None,
            opening_stock=self._to_float(self.opening_stock_input.text()),
            reorder_level=self._to_float(self.reorder_level_input.text()),
        )

        try:
            username = SessionContext.get_username()
            if self._editing_item_id is None:
                self.item_service.add_item(**fields, created_by=username)
            else:
                self.item_service.update_item(self._editing_item_id, **fields, modified_by=username)
        except Exception as exc:
            action = "add" if self._editing_item_id is None else "update"
            logger.exception("Failed to %s item", action)
            QMessageBox.critical(self, "Error", f"Could not {action} item:\n{exc}")
            return

        self.on_cancel_edit()  # clears inputs and leaves edit mode
        self.refresh_items()

    def on_edit_selected(self):
        """Load the selected item into the form and enter edit mode."""
        row = self.table.currentRow()
        if row < 0 or row >= len(self._items):
            QMessageBox.warning(self, "No selection", "Select an item in the table first.")
            return

        item = self._items[row]
        self.code_input.setText(item["code"])
        self.name_input.setText(item["name"])
        self.hsn_input.setText(item["hsn_code"] or "")
        self.gst_input.setText(str(item["gst_rate"]))
        self.unit_input.setText(item["unit"] or "")
        self.opening_stock_input.setText(str(item["opening_stock"]))
        self.reorder_level_input.setText(str(item["reorder_level"]))

        self._editing_item_id = item["id"]
        self.add_button.setText("Update Item")
        self.cancel_button.setVisible(True)
        self.edit_button.setEnabled(False)

    def on_cancel_edit(self):
        """Leave edit mode and reset the form back to 'add' state."""
        self._editing_item_id = None
        self._clear_inputs()
        self.add_button.setText("Add Item")
        self.cancel_button.setVisible(False)
        self.edit_button.setEnabled(True)

    def refresh_items(self):
        items = self.item_service.list_items()
        self._items = items
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = [
                item["id"], item["code"], item["name"], item["hsn_code"] or "",
                item["gst_rate"], item["unit"] or "", item["opening_stock"],
                item["reorder_level"], item["current_stock"],
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))

    def _clear_inputs(self):
        for field in (
            self.code_input, self.name_input, self.hsn_input, self.gst_input,
            self.unit_input, self.opening_stock_input, self.reorder_level_input,
        ):
            field.clear()

    @staticmethod
    def _to_float(text: str) -> float:
        text = text.strip()
        return float(text) if text else 0.0
