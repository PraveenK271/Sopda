"""Verify & Lock screen (historical import H6).

Reconcile what the system shows against a physical count / the book, review any
item that went negative during import, then lock the period. Locking is enforced
in the services (PeriodLockService), so this screen only drives it. UI only.
"""

import logging
from datetime import date

from sqlalchemy import false
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from database import get_session
from models import ImportLog, JournalEntryLine, LedgerAccount
from services.accounting_service import AccountingService
from services.item_service import ItemService
from services.period_lock_service import PeriodLockService
from services.session_context import SessionContext

logger = logging.getLogger(__name__)
_DIFF_COLOR = QColor("#b00020")


class _ReconTable(QWidget):
    """A table: Name | System | (editable) Counted | Difference."""

    def __init__(self, name_header: str, counted_header: str):
        super().__init__()
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([name_header, "System", counted_header, "Difference"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def load(self, rows):
        """rows: list of (name, system_value)."""
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, (name, system) in enumerate(rows):
            name_item = QTableWidgetItem(str(name))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            sys_item = QTableWidgetItem(f"{float(system):.2f}")
            sys_item.setFlags(sys_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            sys_item.setData(Qt.ItemDataRole.UserRole, float(system))
            counted = QTableWidgetItem("")  # user types here
            diff = QTableWidgetItem("")
            diff.setFlags(diff.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 0, name_item)
            self.table.setItem(r, 1, sys_item)
            self.table.setItem(r, 2, counted)
            self.table.setItem(r, 3, diff)
        self.table.blockSignals(False)

    def _on_cell_changed(self, row, col):
        if col != 2:
            return
        sys_val = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole) or 0.0
        text = self.table.item(row, 2).text().strip()
        diff_item = self.table.item(row, 3)
        if text == "":
            diff_item.setText("")
            return
        try:
            counted = float(text)
        except ValueError:
            diff_item.setText("?")
            return
        diff = round(counted - sys_val, 2)
        diff_item.setText(f"{diff:.2f}")
        color = _DIFF_COLOR if abs(diff) > 0.001 else QColor("black")
        for c in range(4):
            self.table.item(row, c).setForeground(QBrush(color))


class VerifyAndLockScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.lock_service = PeriodLockService()
        self.item_service = ItemService()

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-weight:600;")

        self.lock_date = QDateEdit()
        self.lock_date.setDisplayFormat("dd-MM-yyyy")
        self.lock_date.setCalendarPopup(True)
        self.lock_date.setDate(QDate(2026, 7, 31))
        self.lock_reason = QLineEdit()
        self.lock_reason.setPlaceholderText("Reason (e.g. FY2026-27 opening history verified)")
        lock_btn = QPushButton("Lock Period")
        lock_btn.clicked.connect(self.on_lock)
        unlock_btn = QPushButton("Unlock…")
        unlock_btn.clicked.connect(self.on_unlock)

        lock_row = QHBoxLayout()
        lock_row.addWidget(QLabel("Lock up to:"))
        lock_row.addWidget(self.lock_date)
        lock_row.addWidget(self.lock_reason)
        lock_row.addWidget(lock_btn)
        lock_row.addWidget(unlock_btn)

        self.stock_tab = _ReconTable("Item", "Physical")
        self.cust_tab = _ReconTable("Customer", "Book")
        self.supp_tab = _ReconTable("Supplier", "Book")
        self.cash_tab = _ReconTable("Account", "Actual")
        self.warnings_table = QTableWidget()
        self.warnings_table.setColumnCount(3)
        self.warnings_table.setHorizontalHeaderLabels(["File", "Type", "Notes"])
        self.warnings_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        tabs = QTabWidget()
        tabs.addTab(self.stock_tab, "Stock")
        tabs.addTab(self.cust_tab, "Customer Outstanding")
        tabs.addTab(self.supp_tab, "Supplier Outstanding")
        tabs.addTab(self.cash_tab, "Cash / Bank")
        tabs.addTab(self.warnings_table, "Import Warnings")

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addLayout(lock_row)
        layout.addWidget(refresh_btn)
        layout.addWidget(tabs)
        self.setLayout(layout)

        self.refresh()

    def on_lock(self):
        upto = self.lock_date.date().toPython()
        reason = self.lock_reason.text().strip() or None
        confirm = QMessageBox.question(
            self, "Lock Period",
            f"Lock all records dated on or before {upto.strftime('%d-%m-%Y')}? "
            "New entries in that range will be refused until an Administrator unlocks.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self.lock_service.lock(upto, SessionContext.get_username(), reason)
        except ValueError as exc:
            QMessageBox.warning(self, "Lock Period", str(exc))
            return
        self.refresh()

    def on_unlock(self):
        reason, ok = QInputDialog.getText(self, "Unlock", "Reason for unlocking (required):")
        if not ok:
            return
        try:
            self.lock_service.unlock(SessionContext.get_username(), reason)
        except ValueError as exc:
            QMessageBox.warning(self, "Unlock", str(exc))
            return
        self.refresh()

    def refresh(self):
        lock = self.lock_service.current_lock()
        if lock is not None:
            self.status_label.setText(
                f"LOCKED up to {lock.locked_upto_date.strftime('%d-%m-%Y')} "
                f"by {lock.locked_by or '—'}" + (f" ({lock.reason})" if lock.reason else "")
            )
            self.status_label.setStyleSheet("font-weight:600; color:#0f766e;")
        else:
            self.status_label.setText("No active lock.")
            self.status_label.setStyleSheet("font-weight:600; color:#9c6500;")

        # Stock — system figure is the derived current stock (== get_current_stock).
        self.stock_tab.load([
            (f"{it['code']} — {it['name']}", it["current_stock"]) for it in self.item_service.list_items()
        ])
        self.cust_tab.load([(r["name"], r["outstanding"]) for r in AccountingService.get_outstanding_customers()])
        self.supp_tab.load([(r["name"], r["outstanding"]) for r in AccountingService.get_outstanding_suppliers()])
        self.cash_tab.load(self._cash_bank_balances())
        self._load_warnings()

    @staticmethod
    def _cash_bank_balances():
        session = get_session()
        try:
            ledgers = (
                session.query(LedgerAccount)
                .filter(
                    LedgerAccount.account_group.in_(["Cash-in-hand", "Bank Accounts"]),
                    LedgerAccount.is_deleted == false(),
                )
                .order_by(LedgerAccount.name)
                .all()
            )
            rows = []
            for lg in ledgers:
                opening = float(lg.opening_balance) * (-1 if lg.opening_balance_type == "Cr" else 1)
                lines = session.query(JournalEntryLine).filter(JournalEntryLine.account_id == lg.id).all()
                bal = opening + sum(float(l.debit) - float(l.credit) for l in lines)
                rows.append((lg.name, bal))
            return rows
        finally:
            session.close()

    def _load_warnings(self):
        session = get_session()
        try:
            logs = (
                session.query(ImportLog)
                .filter(ImportLog.notes.isnot(None), ImportLog.is_deleted == false())
                .order_by(ImportLog.id.desc())
                .all()
            )
            self.warnings_table.setRowCount(len(logs))
            for r, log in enumerate(logs):
                for c, val in enumerate((log.file_name, log.import_type, log.notes)):
                    self.warnings_table.setItem(r, c, QTableWidgetItem(str(val)))
        finally:
            session.close()
