"""Outstanding screen: customers who owe us / suppliers we owe."""

import logging

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.accounting_service import AccountingService

logger = logging.getLogger(__name__)


class OutstandingScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        top_row = QHBoxLayout()
        top_row.addWidget(self.refresh_button)
        top_row.addStretch()

        self.cust_table = QTableWidget()
        self.cust_table.setColumnCount(3)
        self.cust_table.setHorizontalHeaderLabels(["Customer", "GSTIN", "Outstanding"])
        self.cust_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.cust_table.setAlternatingRowColors(True)
        self.cust_total_label = QLabel("")

        self.supp_table = QTableWidget()
        self.supp_table.setColumnCount(3)
        self.supp_table.setHorizontalHeaderLabels(["Supplier", "GSTIN", "Outstanding"])
        self.supp_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.supp_table.setAlternatingRowColors(True)
        self.supp_total_label = QLabel("")

        layout = QVBoxLayout()
        layout.addLayout(top_row)
        layout.addWidget(QLabel("Customers Outstanding (Receivables)"))
        layout.addWidget(self.cust_table)
        layout.addWidget(self.cust_total_label)
        layout.addWidget(QLabel("Suppliers Outstanding (Payables)"))
        layout.addWidget(self.supp_table)
        layout.addWidget(self.supp_total_label)
        self.setLayout(layout)

    def refresh(self):
        try:
            customers = AccountingService.get_outstanding_customers()
            suppliers = AccountingService.get_outstanding_suppliers()
        except Exception:
            logger.exception("Failed to load outstanding")
            QMessageBox.critical(self, "Error", "Could not load outstanding balances.")
            return

        self.cust_table.setRowCount(len(customers))
        for i, row in enumerate(customers):
            self.cust_table.setItem(i, 0, QTableWidgetItem(row["name"]))
            self.cust_table.setItem(i, 1, QTableWidgetItem(row["gstin"] or ""))
            self.cust_table.setItem(i, 2, QTableWidgetItem(f"{row['outstanding']:,.2f}"))
        total_rec = sum(r["outstanding"] for r in customers)
        self.cust_total_label.setText(f"Total Receivable: {total_rec:,.2f}")

        self.supp_table.setRowCount(len(suppliers))
        for i, row in enumerate(suppliers):
            self.supp_table.setItem(i, 0, QTableWidgetItem(row["name"]))
            self.supp_table.setItem(i, 1, QTableWidgetItem(row["gstin"] or ""))
            self.supp_table.setItem(i, 2, QTableWidgetItem(f"{row['outstanding']:,.2f}"))
        total_pay = sum(r["outstanding"] for r in suppliers)
        self.supp_total_label.setText(f"Total Payable: {total_pay:,.2f}")
