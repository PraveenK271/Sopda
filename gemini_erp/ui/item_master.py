"""Item Master screen: add an item and view the item list with current stock.

UI only collects input and displays results - all logic lives in ItemService.
"""

import logging

from PySide6.QtWidgets import (
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.item_service import ItemService

logger = logging.getLogger(__name__)


class ItemMasterScreen(QWidget):
    COLUMNS = [
        "ID", "Code", "Name", "HSN Code", "GST %", "Unit",
        "Opening Stock", "Reorder Level", "Current Stock",
    ]

    def __init__(self, item_service: ItemService | None = None):
        super().__init__()
        self.item_service = item_service or ItemService()

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

        self.add_button = QPushButton("Add Item")
        self.add_button.clicked.connect(self.on_add_item)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.add_button)
        layout.addWidget(self.table)
        self.setLayout(layout)

        self.refresh_items()

    def on_add_item(self):
        code = self.code_input.text().strip()
        name = self.name_input.text().strip()
        if not code or not name:
            QMessageBox.warning(self, "Missing data", "Code and Name are required.")
            return

        try:
            self.item_service.add_item(
                code=code,
                name=name,
                hsn_code=self.hsn_input.text().strip() or None,
                gst_rate=self._to_float(self.gst_input.text()),
                unit=self.unit_input.text().strip() or None,
                opening_stock=self._to_float(self.opening_stock_input.text()),
                reorder_level=self._to_float(self.reorder_level_input.text()),
            )
        except Exception as exc:
            logger.exception("Failed to add item")
            QMessageBox.critical(self, "Error", f"Could not add item:\n{exc}")
            return

        self._clear_inputs()
        self.refresh_items()

    def refresh_items(self):
        items = self.item_service.list_items()
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            current_stock = self.item_service.get_current_stock(item["id"])
            values = [
                item["id"], item["code"], item["name"], item["hsn_code"] or "",
                item["gst_rate"], item["unit"] or "", item["opening_stock"],
                item["reorder_level"], current_stock,
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
