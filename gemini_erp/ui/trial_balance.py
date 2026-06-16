"""Trial Balance screen: net balance per account as of a date, debit == credit check."""

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


class TrialBalanceScreen(QWidget):
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

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Account", "Group", "Debit", "Credit"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        self.totals_label = QLabel("")

        layout = QVBoxLayout()
        layout.addLayout(filter_row)
        layout.addWidget(self.table)
        layout.addWidget(self.totals_label)
        self.setLayout(layout)

    def refresh(self):
        as_of = self.as_of_date.date().toPython()

        try:
            rows = AccountingService.get_trial_balance(as_of)
        except Exception:
            logger.exception("Failed to load trial balance")
            QMessageBox.critical(self, "Error", "Could not load trial balance.")
            return

        self.table.setRowCount(len(rows))
        total_dr = total_cr = 0.0
        for row_idx, row in enumerate(rows):
            self.table.setItem(row_idx, 0, QTableWidgetItem(row["account_name"]))
            self.table.setItem(row_idx, 1, QTableWidgetItem(row["account_group"]))
            self.table.setItem(row_idx, 2, QTableWidgetItem(
                f"{row['debit']:,.2f}" if row["debit"] else ""
            ))
            self.table.setItem(row_idx, 3, QTableWidgetItem(
                f"{row['credit']:,.2f}" if row["credit"] else ""
            ))
            total_dr += row["debit"]
            total_cr += row["credit"]

        balanced = abs(total_dr - total_cr) < 0.01
        status = "BALANCED ✓" if balanced else f"NOT BALANCED — difference {abs(total_dr - total_cr):.2f}"
        self.totals_label.setText(
            f"Total Debit: {total_dr:,.2f}   |   Total Credit: {total_cr:,.2f}   |   {status}"
        )
