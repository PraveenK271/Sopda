"""Day Book screen: all journal entries for a date range, with their lines."""

import logging

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.accounting_service import AccountingService

logger = logging.getLogger(__name__)


class DayBookScreen(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        today = QDate.currentDate()

        self.date_from = QDateEdit()
        self.date_from.setDate(QDate(today.year(), today.month(), 1))
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

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Date", "Ref", "Narration / Account", "Debit", "Credit"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 100)
        self.tree.setColumnWidth(1, 120)
        self.tree.setColumnWidth(2, 300)
        self.tree.setColumnWidth(3, 100)
        self.tree.setColumnWidth(4, 100)

        layout = QVBoxLayout()
        layout.addLayout(filter_row)
        layout.addWidget(self.tree)
        self.setLayout(layout)

    def refresh(self):
        date_from = self.date_from.date().toPython()
        date_to = self.date_to.date().toPython()

        try:
            entries = AccountingService.get_day_book(date_from, date_to)
        except Exception:
            logger.exception("Failed to load day book")
            QMessageBox.critical(self, "Error", "Could not load day book.")
            return

        self.tree.clear()
        for entry in entries:
            ref = f"{entry['reference_type']}/{entry['reference_id'] or ''}"
            top = QTreeWidgetItem([
                str(entry["date"]),
                ref,
                entry["narration"],
                "",
                "",
            ])
            for line in entry["lines"]:
                dr_text = f"{line['debit']:.2f}" if line["debit"] else ""
                cr_text = f"{line['credit']:.2f}" if line["credit"] else ""
                child = QTreeWidgetItem(["", "", f"    {line['account_name']}", dr_text, cr_text])
                top.addChild(child)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()
