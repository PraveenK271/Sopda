"""Opening Balances screen (historical import H2).

Enter the opening position AS OF 31-03-2026 — opening stock (quantity), party
balances, and cash/bank — by hand or from Excel, then post the one-time opening
journal. UI only; all logic is in OpeningBalanceService / ImportService.

THE BIG RISK (shown on screen): opening stock is the stock ON 31-03-2026, NOT
today's physical count. This year's purchases/sales are imported on top.
"""

import logging
from datetime import date

from sqlalchemy import false
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from database import get_session
from models import LedgerAccount
from services.accounting_service import AccountingService
from services.chart_of_accounts import OPENING_EQUITY
from services.customer_service import CustomerService
from services.import_service import IMPORT_DEFS, ImportService
from services.item_service import ItemService
from services.opening_balance_service import CUTOFF_DATE, OpeningBalanceService
from services.session_context import SessionContext
from services.supplier_service import SupplierService

logger = logging.getLogger(__name__)


class OpeningBalancesScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.obs = OpeningBalanceService()
        self.import_service = ImportService()
        self.item_service = ItemService()
        self.customer_service = CustomerService()
        self.supplier_service = SupplierService()

        warning = QLabel(
            "Opening balances AS OF 31-03-2026 (the cut-off).\n"
            "Opening stock is the stock ON 31-03-2026 — NOT today's count. "
            "This year's purchases/sales are imported on top.\n"
            "Correct: 60 on 31 Mar + 80 bought − 40 sold = 100 today.  "
            "Wrong: 100 (today) + 80 − 40 = 140."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color:#b00020; font-weight:600;")

        tabs = QTabWidget()
        tabs.addTab(self._build_stock_tab(), "Opening Stock")
        tabs.addTab(self._build_party_tab(), "Party Balances")
        tabs.addTab(self._build_cash_tab(), "Cash / Bank")

        self.post_button = QPushButton("Post Opening Journal")
        self.post_button.clicked.connect(self.on_post)
        self.status_label = QLabel("")

        layout = QVBoxLayout()
        layout.addWidget(warning)
        layout.addWidget(tabs)
        layout.addWidget(self.post_button)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

        self.refresh()

    # --- Opening Stock ---------------------------------------------------
    def _build_stock_tab(self):
        w = QWidget()
        self.stock_item_combo = QComboBox()
        self.stock_qty_input = QLineEdit()
        set_btn = QPushButton("Set Opening Stock")
        set_btn.clicked.connect(self.on_set_stock)
        import_btn = QPushButton("Import from Excel")
        import_btn.clicked.connect(lambda: self._import("OPENING_STOCK"))

        form = QFormLayout()
        form.addRow("Item", self.stock_item_combo)
        form.addRow("Opening Qty (on 31-03-2026)", self.stock_qty_input)
        buttons = QHBoxLayout()
        buttons.addWidget(set_btn)
        buttons.addWidget(import_btn)
        box = QVBoxLayout()
        box.addLayout(form)
        box.addLayout(buttons)
        w.setLayout(box)
        return w

    def on_set_stock(self):
        item_id = self.stock_item_combo.currentData()
        if item_id is None:
            return
        try:
            qty = float(self.stock_qty_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Opening Stock", "Enter a valid quantity.")
            return
        self._run(lambda s: self.obs.set_opening_stock(s, item_id, qty, SessionContext.get_username()),
                  "Opening stock set.")

    # --- Party Balances --------------------------------------------------
    def _build_party_tab(self):
        w = QWidget()
        self.party_type_combo = QComboBox()
        self.party_type_combo.addItems(["CUSTOMER", "SUPPLIER"])
        self.party_type_combo.currentTextChanged.connect(self._refresh_party_combo)
        self.party_combo = QComboBox()
        self.party_amount_input = QLineEdit()
        self.party_bt_combo = QComboBox()
        self.party_bt_combo.addItems(["Dr", "Cr"])
        set_btn = QPushButton("Set Party Balance")
        set_btn.clicked.connect(self.on_set_party)
        import_btn = QPushButton("Import from Excel")
        import_btn.clicked.connect(lambda: self._import("OPENING_BALANCES"))

        form = QFormLayout()
        form.addRow("Party Type", self.party_type_combo)
        form.addRow("Party", self.party_combo)
        form.addRow("Amount", self.party_amount_input)
        form.addRow("Balance (Dr owed to us / Cr we owe)", self.party_bt_combo)
        buttons = QHBoxLayout()
        buttons.addWidget(set_btn)
        buttons.addWidget(import_btn)
        box = QVBoxLayout()
        box.addLayout(form)
        box.addLayout(buttons)
        w.setLayout(box)
        return w

    def on_set_party(self):
        party_id = self.party_combo.currentData()
        if party_id is None:
            return
        try:
            amount = float(self.party_amount_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Party Balance", "Enter a valid amount.")
            return
        ptype = self.party_type_combo.currentText()
        bt = self.party_bt_combo.currentText()
        self._run(
            lambda s: self.obs.set_party_opening_balance(s, ptype, party_id, amount, bt, SessionContext.get_username()),
            "Party opening balance set.",
        )

    # --- Cash / Bank -----------------------------------------------------
    def _build_cash_tab(self):
        w = QWidget()
        self.cash_combo = QComboBox()
        self.cash_amount_input = QLineEdit()
        set_btn = QPushButton("Set Cash/Bank Balance")
        set_btn.clicked.connect(self.on_set_cash)
        form = QFormLayout()
        form.addRow("Account", self.cash_combo)
        form.addRow("Amount", self.cash_amount_input)
        box = QVBoxLayout()
        box.addLayout(form)
        box.addWidget(set_btn)
        w.setLayout(box)
        return w

    def on_set_cash(self):
        ledger_id = self.cash_combo.currentData()
        if ledger_id is None:
            return
        try:
            amount = float(self.cash_amount_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, "Cash/Bank", "Enter a valid amount.")
            return
        self._run(lambda s: self.obs.set_cash_bank_opening(s, ledger_id, amount, SessionContext.get_username()),
                  "Cash/bank opening balance set.")

    # --- Post + shared ---------------------------------------------------
    def on_post(self):
        confirm = QMessageBox.question(
            self, "Post Opening Journal",
            "Post the one-time opening journal from the entered balances? "
            "Back up the database first if you have not.",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        session = get_session()
        try:
            entry = self.obs.post_opening_journal(session, CUTOFF_DATE, SessionContext.get_username())
        except ValueError as exc:
            QMessageBox.warning(self, "Post Opening Journal", str(exc))
            return
        except Exception as exc:
            logger.exception("Post opening journal failed")
            QMessageBox.critical(self, "Post Opening Journal", f"Failed:\n{exc}")
            return
        finally:
            session.close()
        QMessageBox.information(self, "Post Opening Journal", f"Opening journal posted (entry id={entry.id}).")
        self.refresh()

    def _run(self, action, ok_message):
        session = get_session()
        try:
            action(session)
        except ValueError as exc:
            QMessageBox.warning(self, "Opening Balances", str(exc))
            return
        except Exception as exc:
            logger.exception("Opening balance action failed")
            QMessageBox.critical(self, "Opening Balances", f"Failed:\n{exc}")
            return
        finally:
            session.close()
        self.status_label.setText(ok_message)
        self.refresh()

    def _import(self, import_type):
        path, _ = QFileDialog.getOpenFileName(self, "Choose file", "", "Excel Files (*.xlsx)")
        if not path:
            return
        # Validate first (two-stage contract).
        try:
            rows = self.import_service.read_sheet(path, IMPORT_DEFS[import_type].column_names())
            report = self.import_service.validate(rows, import_type)
        except Exception as exc:
            QMessageBox.critical(self, "Import", f"Could not read the file:\n{exc}")
            return
        if not report.is_importable:
            msg = "\n".join(f"Row {e['row_number']}: {e['message']}" for e in report.errors[:15])
            QMessageBox.warning(self, "Import — errors found", f"{len(report.errors)} error(s):\n{msg}")
            return
        try:
            log = self.import_service.import_data(import_type, path, SessionContext.get_username())
        except Exception as exc:
            logger.exception("Import failed")
            QMessageBox.critical(self, "Import", f"Import stopped:\n{exc}")
            return
        QMessageBox.information(self, "Import", f"Imported {log.records_created} record(s).")
        self.refresh()

    def _refresh_party_combo(self):
        ptype = self.party_type_combo.currentText()
        self.party_combo.clear()
        parties = (
            self.customer_service.list_customers() if ptype == "CUSTOMER"
            else self.supplier_service.list_suppliers()
        )
        for p in parties:
            self.party_combo.addItem(p["name"], p["id"])

    def refresh(self):
        # Item picker.
        self.stock_item_combo.clear()
        for it in self.item_service.list_items():
            self.stock_item_combo.addItem(f"{it['code']} — {it['name']}", it["id"])
        # Party picker.
        self._refresh_party_combo()
        # Cash/bank ledgers.
        self.cash_combo.clear()
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
            for lg in ledgers:
                self.cash_combo.addItem(lg.name, lg.id)
            # Enable Post only when there are staged (non-zero) opening balances.
            equity = (
                session.query(LedgerAccount).filter(LedgerAccount.code == OPENING_EQUITY).first()
            )
            equity_id = equity.id if equity else -1
            staged = (
                session.query(LedgerAccount)
                .filter(
                    LedgerAccount.opening_balance != 0,
                    LedgerAccount.is_deleted == false(),
                    LedgerAccount.id != equity_id,
                )
                .count()
            )
        finally:
            session.close()
        self.post_button.setEnabled(staged > 0)
