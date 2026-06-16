"""Profit & Loss screen: income vs expenses for a period, net profit."""

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


class ProfitAndLossScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        today = QDate.currentDate()

        self.date_from = QDateEdit()
        self.date_from.setDate(QDate(today.year(), 4, 1))  # Indian FY start
        self.date_from.setCalendarPopup(True)

        self.date_to = QDateEdit()
        self.date_to.setDate(today)
        self.date_to.setCalendarPopup(True)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("From"))
        filter_row.addWidget(self.date_from)
        filter_row.addWidget(QLabel("To"))
        filter_row.addWidget(self.date_to)
        filter_row.addWidget(self.refresh_button)
        filter_row.addStretch()

        self.income_label = QLabel("Income")
        self.income_table = QTableWidget()
        self.income_table.setColumnCount(3)
        self.income_table.setHorizontalHeaderLabels(["Account", "Group", "Amount"])
        self.income_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.income_table.setAlternatingRowColors(True)
        self.income_total_label = QLabel("")

        self.expense_label = QLabel("Expenses")
        self.expense_table = QTableWidget()
        self.expense_table.setColumnCount(3)
        self.expense_table.setHorizontalHeaderLabels(["Account", "Group", "Amount"])
        self.expense_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.expense_table.setAlternatingRowColors(True)
        self.expense_total_label = QLabel("")

        self.net_profit_label = QLabel("")

        layout = QVBoxLayout()
        layout.addLayout(filter_row)
        layout.addWidget(self.income_label)
        layout.addWidget(self.income_table)
        layout.addWidget(self.income_total_label)
        layout.addWidget(self.expense_label)
        layout.addWidget(self.expense_table)
        layout.addWidget(self.expense_total_label)
        layout.addWidget(self.net_profit_label)
        self.setLayout(layout)

    def refresh(self):
        date_from = self.date_from.date().toPython()
        date_to = self.date_to.date().toPython()

        try:
            pl = AccountingService.get_profit_and_loss(date_from, date_to)
        except Exception:
            logger.exception("Failed to load P&L")
            QMessageBox.critical(self, "Error", "Could not load Profit & Loss.")
            return

        self._fill_table(self.income_table, pl["income"])
        total_income = sum(r["amount"] for r in pl["income"])
        self.income_total_label.setText(f"Total Income: {total_income:,.2f}")

        self._fill_table(self.expense_table, pl["expenses"])
        total_expenses = sum(r["amount"] for r in pl["expenses"])
        self.expense_total_label.setText(f"Total Expenses: {total_expenses:,.2f}")

        net = pl["net_profit"]
        label = "Net Profit" if net >= 0 else "Net Loss"
        self.net_profit_label.setText(f"{label}: {abs(net):,.2f}")

    @staticmethod
    def _fill_table(table: QTableWidget, rows: list[dict]):
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(row["account_name"]))
            table.setItem(i, 1, QTableWidgetItem(row["account_group"]))
            table.setItem(i, 2, QTableWidgetItem(f"{row['amount']:,.2f}"))
