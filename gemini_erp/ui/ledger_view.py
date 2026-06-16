"""Ledger view screen: running balance for a single account over a date range."""

import logging

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
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

from services.accounting_service import AccountingService

logger = logging.getLogger(__name__)


class LedgerViewScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        today = QDate.currentDate()

        self.account_combo = QComboBox()

        self.date_from = QDateEdit()
        self.date_from.setDate(QDate(today.year(), 4, 1))  # Indian FY start
        self.date_from.setCalendarPopup(True)

        self.date_to = QDateEdit()
        self.date_to.setDate(today)
        self.date_to.setCalendarPopup(True)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        account_row = QFormLayout()
        account_row.addRow("Account", self.account_combo)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("From"))
        date_row.addWidget(self.date_from)
        date_row.addWidget(QLabel("To"))
        date_row.addWidget(self.date_to)
        date_row.addWidget(self.refresh_button)
        date_row.addStretch()

        self.opening_label = QLabel("")
        self.closing_label = QLabel("")

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Date", "Narration", "Debit", "Credit", "Balance"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        layout = QVBoxLayout()
        layout.addLayout(account_row)
        layout.addLayout(date_row)
        layout.addWidget(self.opening_label)
        layout.addWidget(self.table)
        layout.addWidget(self.closing_label)
        self.setLayout(layout)

    def refresh_accounts(self):
        current_id = None
        current_data = self.account_combo.currentData()
        if current_data:
            current_id = current_data["id"]

        try:
            accounts = AccountingService.list_accounts()
        except Exception:
            logger.exception("Failed to load account list")
            return

        self.account_combo.clear()
        for acct in accounts:
            label = f"{acct['name']} ({acct['account_group']})"
            self.account_combo.addItem(label, acct)
            if acct["id"] == current_id:
                self.account_combo.setCurrentIndex(self.account_combo.count() - 1)

    def refresh(self):
        acct_data = self.account_combo.currentData()
        if acct_data is None:
            return

        date_from = self.date_from.date().toPython()
        date_to = self.date_to.date().toPython()

        try:
            ledger = AccountingService.get_ledger(acct_data["id"], date_from, date_to)
        except Exception:
            logger.exception("Failed to load ledger")
            QMessageBox.critical(self, "Error", "Could not load ledger.")
            return

        ob = ledger["opening_balance"]
        self.opening_label.setText(
            f"Opening Balance: {ob:,.2f} {ledger['opening_balance_type']}"
        )

        entries = ledger["entries"]
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            dr_text = f"{entry['debit']:,.2f}" if entry["debit"] else ""
            cr_text = f"{entry['credit']:,.2f}" if entry["credit"] else ""
            balance_text = f"{entry['balance']:,.2f} {entry['balance_type']}"
            self.table.setItem(row, 0, QTableWidgetItem(str(entry["date"])))
            self.table.setItem(row, 1, QTableWidgetItem(entry["narration"]))
            self.table.setItem(row, 2, QTableWidgetItem(dr_text))
            self.table.setItem(row, 3, QTableWidgetItem(cr_text))
            self.table.setItem(row, 4, QTableWidgetItem(balance_text))

        cb = ledger["closing_balance"]
        self.closing_label.setText(
            f"Closing Balance: {cb:,.2f} {ledger['closing_balance_type']}"
        )
