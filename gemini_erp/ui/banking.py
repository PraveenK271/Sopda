"""Banking screens: Bank Accounts, Receipts, Payments.

UI only collects input and displays results — all posting (and the journal
entry behind every receipt/payment) lives in BankingService.
"""

import logging
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QHBoxLayout,
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

from services.banking_service import BankingService
from services.customer_service import CustomerService
from services.supplier_service import SupplierService

logger = logging.getLogger(__name__)


class BankAccountsTab(QWidget):
    COLUMNS = ["ID", "Name", "Bank", "Account No", "IFSC", "Opening Balance"]

    # Emitted after the bank-account list changes so sibling tabs (Receipts /
    # Payments / Reconciliation) can refresh their bank-account dropdowns.
    accounts_changed = Signal()

    def __init__(self, banking: BankingService):
        super().__init__()
        self.banking = banking
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        self.name_input = QLineEdit()
        self.bank_name_input = QLineEdit()
        self.account_no_input = QLineEdit()
        self.ifsc_input = QLineEdit()
        self.opening_input = QLineEdit()

        form = QFormLayout()
        form.addRow("Account Name", self.name_input)
        form.addRow("Bank Name", self.bank_name_input)
        form.addRow("Account No", self.account_no_input)
        form.addRow("IFSC", self.ifsc_input)
        form.addRow("Opening Balance", self.opening_input)

        self.add_button = QPushButton("Add Bank Account")
        self.add_button.clicked.connect(self.on_add)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.add_button)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def on_add(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing data", "Account name is required.")
            return
        try:
            opening = self.opening_input.text().strip()
            self.banking.add_bank_account(
                name=name,
                bank_name=self.bank_name_input.text().strip() or None,
                account_no=self.account_no_input.text().strip() or None,
                ifsc=self.ifsc_input.text().strip() or None,
                opening_balance=float(opening) if opening else 0.0,
            )
        except Exception as exc:
            logger.exception("Failed to add bank account")
            QMessageBox.critical(self, "Error", f"Could not add bank account:\n{exc}")
            return

        for field in (
            self.name_input, self.bank_name_input, self.account_no_input,
            self.ifsc_input, self.opening_input,
        ):
            field.clear()
        self.refresh()
        # Let the Receipts/Payments/Reconciliation tabs pick up the new account
        # right away, instead of only when Banking is re-entered.
        self.accounts_changed.emit()

    def refresh(self):
        banks = self.banking.list_bank_accounts()
        self.table.setRowCount(len(banks))
        for row, b in enumerate(banks):
            values = [
                b["id"], b["name"], b["bank_name"] or "", b["account_no"] or "",
                b["ifsc"] or "", f"{b['opening_balance']:,.2f}",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))


class _MoneyMoveTab(QWidget):
    """Shared layout for Receipts and Payments (they differ only in party + posting)."""

    PARTY_LABEL = "Party"
    RECORD_LABEL = "Record"
    COLUMNS = ["Date", "Party", "Mode", "Bank", "Amount", "Reference", "Notes"]

    def __init__(self, banking: BankingService):
        super().__init__()
        self.banking = banking
        self._build_ui()

    def _build_ui(self):
        self.date_input = QDateEdit()
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setCalendarPopup(True)

        self.party_combo = QComboBox()
        self.amount_input = QLineEdit()

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["CASH", "BANK"])
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)

        self.bank_combo = QComboBox()
        self.bank_combo.setEnabled(False)

        self.reference_input = QLineEdit()
        self.notes_input = QLineEdit()

        form = QFormLayout()
        form.addRow("Date", self.date_input)
        form.addRow(self.PARTY_LABEL, self.party_combo)
        form.addRow("Amount", self.amount_input)
        form.addRow("Mode", self.mode_combo)
        form.addRow("Bank Account", self.bank_combo)
        form.addRow("Reference No", self.reference_input)
        form.addRow("Notes", self.notes_input)

        self.record_button = QPushButton(self.RECORD_LABEL)
        self.record_button.clicked.connect(self.on_record)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.record_button)
        layout.addWidget(self.table)
        self.setLayout(layout)

    def _on_mode_changed(self, mode: str):
        self.bank_combo.setEnabled(mode == "BANK")

    def refresh_lookups(self):
        # Parties (customers/suppliers) — implemented by subclass.
        self._refresh_parties()

        current_bank_id = None
        current = self.bank_combo.currentData()
        if current:
            current_bank_id = current["id"]
        self.bank_combo.clear()
        for b in self.banking.list_bank_accounts():
            self.bank_combo.addItem(f"{b['name']} ({b['bank_name'] or ''})", b)
            if b["id"] == current_bank_id:
                self.bank_combo.setCurrentIndex(self.bank_combo.count() - 1)

        self.refresh()

    def _validated_inputs(self):
        party = self.party_combo.currentData()
        if party is None:
            QMessageBox.warning(self, "Missing data", f"Select a {self.PARTY_LABEL.lower()}.")
            return None
        try:
            amount = Decimal(self.amount_input.text().strip())
        except (InvalidOperation, ValueError):
            QMessageBox.warning(self, "Invalid input", "Amount must be a number.")
            return None
        if amount <= 0:
            QMessageBox.warning(self, "Invalid input", "Amount must be greater than zero.")
            return None

        mode = self.mode_combo.currentText()
        bank_account_id = None
        if mode == "BANK":
            bank = self.bank_combo.currentData()
            if bank is None:
                QMessageBox.warning(self, "Missing data", "Select a bank account for BANK mode.")
                return None
            bank_account_id = bank["id"]

        return {
            "date": self.date_input.date().toPython(),
            "party_id": party["id"],
            "amount": float(amount),
            "payment_mode": mode,
            "bank_account_id": bank_account_id,
            "reference_no": self.reference_input.text().strip() or None,
            "notes": self.notes_input.text().strip() or None,
        }

    def _clear_inputs(self):
        self.amount_input.clear()
        self.reference_input.clear()
        self.notes_input.clear()

    def _fill_table(self, rows):
        self.table.setRowCount(len(rows))
        for row, r in enumerate(rows):
            values = [
                str(r["date"]),
                r["party_name"],
                r["payment_mode"],
                r["bank_account_name"] or "",
                f"{r['amount']:,.2f}",
                r["reference_no"] or "",
                r["notes"] or "",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))

    # --- subclass hooks ---
    def _refresh_parties(self):
        raise NotImplementedError

    def on_record(self):
        raise NotImplementedError

    def refresh(self):
        raise NotImplementedError


class ReceiptsTab(_MoneyMoveTab):
    PARTY_LABEL = "Customer"
    RECORD_LABEL = "Record Receipt"
    COLUMNS = ["Date", "Customer", "Mode", "Bank", "Amount", "Reference", "Notes"]

    def __init__(self, banking: BankingService):
        self.customer_service = CustomerService()
        super().__init__(banking)

    def _refresh_parties(self):
        current_id = None
        current = self.party_combo.currentData()
        if current:
            current_id = current["id"]
        self.party_combo.clear()
        for c in self.customer_service.list_customers():
            self.party_combo.addItem(f"{c['name']}", c)
            if c["id"] == current_id:
                self.party_combo.setCurrentIndex(self.party_combo.count() - 1)

    def on_record(self):
        data = self._validated_inputs()
        if data is None:
            return
        try:
            self.banking.record_receipt(
                date=data["date"], customer_id=data["party_id"], amount=data["amount"],
                payment_mode=data["payment_mode"], bank_account_id=data["bank_account_id"],
                reference_no=data["reference_no"], notes=data["notes"],
            )
        except Exception as exc:
            logger.exception("Failed to record receipt")
            QMessageBox.critical(self, "Error", f"Could not record receipt:\n{exc}")
            return
        QMessageBox.information(self, "Saved", "Receipt recorded.")
        self._clear_inputs()
        self.refresh()

    def refresh(self):
        rows = [
            {**r, "party_name": r["customer_name"]} for r in self.banking.list_receipts()
        ]
        self._fill_table(rows)


class PaymentsTab(_MoneyMoveTab):
    PARTY_LABEL = "Supplier"
    RECORD_LABEL = "Record Payment"
    COLUMNS = ["Date", "Supplier", "Mode", "Bank", "Amount", "Reference", "Notes"]

    def __init__(self, banking: BankingService):
        self.supplier_service = SupplierService()
        super().__init__(banking)

    def _refresh_parties(self):
        current_id = None
        current = self.party_combo.currentData()
        if current:
            current_id = current["id"]
        self.party_combo.clear()
        for s in self.supplier_service.list_suppliers():
            self.party_combo.addItem(f"{s['name']}", s)
            if s["id"] == current_id:
                self.party_combo.setCurrentIndex(self.party_combo.count() - 1)

    def on_record(self):
        data = self._validated_inputs()
        if data is None:
            return
        try:
            self.banking.record_payment(
                date=data["date"], supplier_id=data["party_id"], amount=data["amount"],
                payment_mode=data["payment_mode"], bank_account_id=data["bank_account_id"],
                reference_no=data["reference_no"], notes=data["notes"],
            )
        except Exception as exc:
            logger.exception("Failed to record payment")
            QMessageBox.critical(self, "Error", f"Could not record payment:\n{exc}")
            return
        QMessageBox.information(self, "Saved", "Payment recorded.")
        self._clear_inputs()
        self.refresh()

    def refresh(self):
        rows = [
            {**p, "party_name": p["supplier_name"]} for p in self.banking.list_payments()
        ]
        self._fill_table(rows)


class ReconciliationTab(QWidget):
    """Manual bank reconciliation: match statement lines to receipts/payments.

    Pick a bank account, optionally add statement lines by hand (no file
    import — see CHECKLIST_PHASE2_PART2.md Decision 4), then select one
    unmatched statement line and the matching receipt/payment and hit Match.
    """

    LINE_COLUMNS = ["Date", "Description", "Type", "Amount"]
    MOVE_COLUMNS = ["Date", "Type", "Party", "Reference", "Amount"]

    def __init__(self, banking: BankingService):
        super().__init__()
        self.banking = banking
        self._build_ui()

    def _build_ui(self):
        self.bank_combo = QComboBox()
        self.bank_combo.currentIndexChanged.connect(self.refresh)

        bank_row = QHBoxLayout()
        bank_row.addWidget(QLabel("Bank Account"))
        bank_row.addWidget(self.bank_combo)
        bank_row.addStretch()

        # Add-a-statement-line form (signed amount: + deposit, - withdrawal).
        self.line_date = QDateEdit()
        self.line_date.setDate(QDate.currentDate())
        self.line_date.setCalendarPopup(True)
        self.line_desc = QLineEdit()
        self.line_amount = QLineEdit()
        self.line_amount.setPlaceholderText("+ deposit / - withdrawal")
        self.add_line_button = QPushButton("Add Statement Line")
        self.add_line_button.clicked.connect(self.on_add_line)

        add_form = QHBoxLayout()
        add_form.addWidget(QLabel("Date"))
        add_form.addWidget(self.line_date)
        add_form.addWidget(QLabel("Description"))
        add_form.addWidget(self.line_desc)
        add_form.addWidget(QLabel("Amount"))
        add_form.addWidget(self.line_amount)
        add_form.addWidget(self.add_line_button)

        # Side-by-side: unmatched statement lines | unmatched receipts+payments.
        self.lines_table = QTableWidget()
        self.lines_table.setColumnCount(len(self.LINE_COLUMNS))
        self.lines_table.setHorizontalHeaderLabels(self.LINE_COLUMNS)
        self.lines_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.lines_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.lines_table.setAlternatingRowColors(True)

        self.moves_table = QTableWidget()
        self.moves_table.setColumnCount(len(self.MOVE_COLUMNS))
        self.moves_table.setHorizontalHeaderLabels(self.MOVE_COLUMNS)
        self.moves_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.moves_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.moves_table.setAlternatingRowColors(True)

        tables_row = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Unmatched statement lines"))
        left.addWidget(self.lines_table)
        right = QVBoxLayout()
        right.addWidget(QLabel("Unmatched receipts / payments"))
        right.addWidget(self.moves_table)
        tables_row.addLayout(left)
        tables_row.addLayout(right)

        self.match_button = QPushButton("Match Selected")
        self.match_button.clicked.connect(self.on_match)

        layout = QVBoxLayout()
        layout.addLayout(bank_row)
        layout.addLayout(add_form)
        layout.addLayout(tables_row)
        layout.addWidget(self.match_button)
        self.setLayout(layout)

    def _current_bank_id(self):
        data = self.bank_combo.currentData()
        return data["id"] if data else None

    def refresh_lookups(self):
        current_id = self._current_bank_id()
        self.bank_combo.blockSignals(True)
        self.bank_combo.clear()
        for b in self.banking.list_bank_accounts():
            self.bank_combo.addItem(f"{b['name']} ({b['bank_name'] or ''})", b)
            if b["id"] == current_id:
                self.bank_combo.setCurrentIndex(self.bank_combo.count() - 1)
        self.bank_combo.blockSignals(False)
        self.refresh()

    def on_add_line(self):
        bank_id = self._current_bank_id()
        if bank_id is None:
            QMessageBox.warning(self, "No bank account", "Add/select a bank account first.")
            return
        try:
            amount = Decimal(self.line_amount.text().strip())
        except (InvalidOperation, ValueError):
            QMessageBox.warning(self, "Invalid input", "Amount must be a number (+ deposit / - withdrawal).")
            return
        try:
            self.banking.add_statement_line(
                bank_account_id=bank_id,
                date=self.line_date.date().toPython(),
                description=self.line_desc.text().strip() or None,
                amount=float(amount),
            )
        except Exception as exc:
            logger.exception("Failed to add statement line")
            QMessageBox.critical(self, "Error", f"Could not add statement line:\n{exc}")
            return
        self.line_desc.clear()
        self.line_amount.clear()
        self.refresh()

    def refresh(self):
        bank_id = self._current_bank_id()
        if bank_id is None:
            self.lines_table.setRowCount(0)
            self.moves_table.setRowCount(0)
            return

        lines = self.banking.list_unmatched_statement_lines(bank_id)
        self.lines_table.setRowCount(len(lines))
        for row, line in enumerate(lines):
            kind = "Deposit" if line["amount"] >= 0 else "Withdrawal"
            cells = [str(line["date"]), line["description"] or "", kind, f"{line['amount']:,.2f}"]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(0x0100, line)  # Qt.UserRole
                self.lines_table.setItem(row, col, item)

        receipts = [{**r, "kind": "Receipt"} for r in self.banking.list_unmatched_receipts(bank_id)]
        payments = [{**p, "kind": "Payment"} for p in self.banking.list_unmatched_payments(bank_id)]
        moves = sorted(receipts + payments, key=lambda m: (str(m["date"]), m["kind"]))
        self.moves_table.setRowCount(len(moves))
        for row, move in enumerate(moves):
            cells = [
                str(move["date"]), move["kind"], move["party_name"],
                move["reference_no"] or "", f"{move['amount']:,.2f}",
            ]
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(0x0100, move)  # Qt.UserRole
                self.moves_table.setItem(row, col, item)

    @staticmethod
    def _selected_payload(table):
        rows = table.selectionModel().selectedRows() if table.selectionModel() else []
        if not rows:
            return None
        return table.item(rows[0].row(), 0).data(0x0100)

    def on_match(self):
        line = self._selected_payload(self.lines_table)
        move = self._selected_payload(self.moves_table)
        if line is None or move is None:
            QMessageBox.warning(self, "Select two rows", "Select one statement line and one receipt/payment.")
            return
        try:
            if move["kind"] == "Receipt":
                self.banking.match_statement_line(line["id"], receipt_id=move["id"])
            else:
                self.banking.match_statement_line(line["id"], payment_id=move["id"])
        except Exception as exc:
            logger.exception("Failed to match statement line")
            QMessageBox.critical(self, "Error", f"Could not match:\n{exc}")
            return
        QMessageBox.information(self, "Matched", "Statement line matched.")
        self.refresh()


class BankingScreen(QTabWidget):
    """Top-level 'Banking' tab: Bank Accounts / Receipts / Payments / Reconciliation."""

    def __init__(self):
        super().__init__()
        self.banking = BankingService()
        self.bank_accounts_tab = BankAccountsTab(self.banking)
        self.receipts_tab = ReceiptsTab(self.banking)
        self.payments_tab = PaymentsTab(self.banking)
        self.reconciliation_tab = ReconciliationTab(self.banking)

        self.addTab(self.bank_accounts_tab, "Bank Accounts")
        self.addTab(self.receipts_tab, "Receipts")
        self.addTab(self.payments_tab, "Payments")
        self.addTab(self.reconciliation_tab, "Reconciliation")

        # Adding a bank account refreshes the tabs that pick from it.
        self.bank_accounts_tab.accounts_changed.connect(self._on_accounts_changed)
        # Also refresh a sub-tab's lookups whenever the user switches to it, so
        # its bank/party dropdowns are never stale within a Banking session.
        self.currentChanged.connect(self._on_sub_tab_changed)

    def _on_accounts_changed(self):
        self.receipts_tab.refresh_lookups()
        self.payments_tab.refresh_lookups()
        self.reconciliation_tab.refresh_lookups()

    def _on_sub_tab_changed(self, index: int):
        widget = self.widget(index)
        if hasattr(widget, "refresh_lookups"):
            widget.refresh_lookups()
        elif hasattr(widget, "refresh"):
            widget.refresh()

    def refresh_all(self):
        self.bank_accounts_tab.refresh()
        self.receipts_tab.refresh_lookups()
        self.payments_tab.refresh_lookups()
        self.reconciliation_tab.refresh_lookups()
