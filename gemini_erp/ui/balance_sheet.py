"""Balance Sheet screen: assets vs liabilities + net profit as of a date."""

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

from services.accounting_service import AccountingService

logger = logging.getLogger(__name__)


class BalanceSheetScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        self.as_of_date = QDateEdit()
        self.as_of_date.setDate(QDate.currentDate())
        self.as_of_date.setCalendarPopup(True)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("As of"))
        filter_row.addWidget(self.as_of_date)
        filter_row.addWidget(self.refresh_button)
        filter_row.addStretch()

        self.assets_label = QLabel("Assets")
        self.assets_table = QTableWidget()
        self.assets_table.setColumnCount(3)
        self.assets_table.setHorizontalHeaderLabels(["Account", "Group", "Amount"])
        self.assets_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.assets_table.setAlternatingRowColors(True)
        self.assets_total_label = QLabel("")

        self.liab_label = QLabel("Liabilities")
        self.liab_table = QTableWidget()
        self.liab_table.setColumnCount(3)
        self.liab_table.setHorizontalHeaderLabels(["Account", "Group", "Amount"])
        self.liab_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.liab_table.setAlternatingRowColors(True)
        self.liab_total_label = QLabel("")

        self.check_label = QLabel("")

        layout = QVBoxLayout()
        layout.addLayout(filter_row)
        layout.addWidget(self.assets_label)
        layout.addWidget(self.assets_table)
        layout.addWidget(self.assets_total_label)
        layout.addWidget(self.liab_label)
        layout.addWidget(self.liab_table)
        layout.addWidget(self.liab_total_label)
        layout.addWidget(self.check_label)
        self.setLayout(layout)

    def refresh(self):
        as_of = self.as_of_date.date().toPython()

        try:
            bs = AccountingService.get_balance_sheet(as_of)
        except Exception:
            logger.exception("Failed to load balance sheet")
            QMessageBox.critical(self, "Error", "Could not load Balance Sheet.")
            return

        self._fill_table(self.assets_table, bs["assets"])
        total_assets = sum(r["amount"] for r in bs["assets"])
        self.assets_total_label.setText(f"Total Assets: {total_assets:,.2f}")

        # Liabilities table includes a synthetic "Profit & Loss A/c" row
        liab_rows = list(bs["liabilities"])
        np = bs["net_profit_to_date"]
        liab_rows.append({
            "account_name": "Profit & Loss A/c (current)",
            "account_group": "Capital Accounts",
            "amount": np,
        })
        self._fill_table(self.liab_table, liab_rows)
        total_liab = sum(r["amount"] for r in liab_rows)
        self.liab_total_label.setText(f"Total Liabilities: {total_liab:,.2f}")

        diff = abs(total_assets - total_liab)
        if diff < 0.01:
            self.check_label.setText("Balance Sheet balances ✓")
        else:
            self.check_label.setText(f"WARNING: out of balance by {diff:,.2f}")

    @staticmethod
    def _fill_table(table: QTableWidget, rows: list[dict]):
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(row["account_name"]))
            table.setItem(i, 1, QTableWidgetItem(row["account_group"]))
            table.setItem(i, 2, QTableWidgetItem(f"{row['amount']:,.2f}"))
