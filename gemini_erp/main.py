"""Application entry point."""

import logging
import os
import sys

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QTabWidget

from create_db import initialize_database
from database import get_app_root
from services.auth_service import AuthService
from services.permissions import (
    MODULE_ACCOUNTS,
    MODULE_BANKING,
    MODULE_BILLING,
    MODULE_DOCUMENTS,
    MODULE_GST,
    MODULE_ITEMS,
    MODULE_PURCHASE_LOG,
    MODULE_PURCHASES,
    MODULE_SALES_LOG,
    MODULE_SETTINGS,
    MODULE_USERS,
)
from services.session_context import SessionContext
from ui.balance_sheet import BalanceSheetScreen
from ui.banking import BankingScreen
from ui.billing import BillingScreen
from ui.change_password import ChangePasswordDialog
from ui.day_book import DayBookScreen
from ui.gst_reports import GstReportsScreen
from ui.gst_returns import GstReturnsScreen
from ui.item_master import ItemMasterScreen
from ui.ledger_view import LedgerViewScreen
from ui.login import LoginDialog
from ui.ocr_purchase import DocumentHistoryScreen, OCRPurchaseScreen
from ui.outstanding import OutstandingScreen
from ui.profit_and_loss import ProfitAndLossScreen
from ui.purchase import PurchaseScreen
from ui.purchase_log import PurchaseLogScreen
from ui.sales_log import SalesLogScreen
from ui.settings import SettingsScreen
from ui.trial_balance import TrialBalanceScreen
from ui.user_management import UserManagementScreen


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.logout_requested = False
        self._refreshers = []

        user = SessionContext.get_user()
        role_name = user.role.name if user and user.role else ""
        display_name = (user.full_name or user.username) if user else ""
        self.setWindowTitle(f"Gemini ERP — {display_name} ({role_name})")
        self.resize(1200, 800)

        self.tabs = QTabWidget()
        self._build_permitted_tabs(user)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.setCentralWidget(self.tabs)

        self._build_menu()

    def _can(self, user, module_key: str) -> bool:
        return AuthService.has_permission(user, module_key)

    def _build_permitted_tabs(self, user):
        """Build ONLY the tabs the role permits — a screen that is never created
        cannot be reached (we do not build-then-hide)."""
        if self._can(user, MODULE_ITEMS):
            self.item_master_screen = ItemMasterScreen()
            self.tabs.addTab(self.item_master_screen, "Items")
            self._refreshers.append(self.item_master_screen.refresh_items)

        if self._can(user, MODULE_BILLING):
            self.billing_screen = BillingScreen()
            self.tabs.addTab(self.billing_screen, "Billing")
            self._refreshers.append(self.billing_screen.refresh_lookups)

        if self._can(user, MODULE_PURCHASES):
            self.purchase_screen = PurchaseScreen()
            self.tabs.addTab(self.purchase_screen, "Purchases")
            self._refreshers.append(self.purchase_screen.refresh_lookups)

        if self._can(user, MODULE_SALES_LOG):
            self.sales_log_screen = SalesLogScreen()
            self.tabs.addTab(self.sales_log_screen, "Sales Log")
            self._refreshers.append(self.sales_log_screen.refresh_invoices)

        if self._can(user, MODULE_PURCHASE_LOG):
            self.purchase_log_screen = PurchaseLogScreen()
            self.tabs.addTab(self.purchase_log_screen, "Purchase Log")
            self._refreshers.append(self.purchase_log_screen.refresh_invoices)
            # Editing a saved purchase needs the Purchases screen too.
            if self._can(user, MODULE_PURCHASES):
                self.purchase_log_screen.edit_requested.connect(self.on_edit_purchase_invoice)

        if self._can(user, MODULE_ACCOUNTS):
            self.day_book_screen = DayBookScreen()
            self.ledger_view_screen = LedgerViewScreen()
            self.trial_balance_screen = TrialBalanceScreen()
            self.pl_screen = ProfitAndLossScreen()
            self.bs_screen = BalanceSheetScreen()
            self.outstanding_screen = OutstandingScreen()
            accounts_tabs = QTabWidget()
            accounts_tabs.addTab(self.day_book_screen, "Day Book")
            accounts_tabs.addTab(self.ledger_view_screen, "Ledger")
            accounts_tabs.addTab(self.trial_balance_screen, "Trial Balance")
            accounts_tabs.addTab(self.pl_screen, "P & L")
            accounts_tabs.addTab(self.bs_screen, "Balance Sheet")
            accounts_tabs.addTab(self.outstanding_screen, "Outstanding")
            self.tabs.addTab(accounts_tabs, "Accounts")
            self._refreshers.append(self.ledger_view_screen.refresh_accounts)

        if self._can(user, MODULE_BANKING):
            self.banking_screen = BankingScreen()
            self.tabs.addTab(self.banking_screen, "Banking")
            self._refreshers.append(self.banking_screen.refresh_all)

        if self._can(user, MODULE_GST):
            self.gst_reports_screen = GstReportsScreen()
            self.gst_returns_screen = GstReturnsScreen()
            gst_tabs = QTabWidget()
            gst_tabs.addTab(self.gst_reports_screen, "Registers/HSN")
            gst_tabs.addTab(self.gst_returns_screen, "Returns")
            self.tabs.addTab(gst_tabs, "GST")
            self._refreshers.append(self.gst_reports_screen.refresh)
            self._refreshers.append(self.gst_returns_screen.refresh)

        if self._can(user, MODULE_DOCUMENTS):
            self.ocr_purchase_screen = OCRPurchaseScreen()
            self.document_history_screen = DocumentHistoryScreen()
            documents_tabs = QTabWidget()
            documents_tabs.addTab(self.ocr_purchase_screen, "Scan Purchase Bill")
            documents_tabs.addTab(self.document_history_screen, "Document History")
            self.tabs.addTab(documents_tabs, "Documents")
            self._refreshers.append(self.ocr_purchase_screen.refresh_lookups)
            self._refreshers.append(self.document_history_screen.refresh)

        if self._can(user, MODULE_SETTINGS):
            self.settings_screen = SettingsScreen()
            self.tabs.addTab(self.settings_screen, "Settings")
            self._refreshers.append(self.settings_screen.refresh)

        if self._can(user, MODULE_USERS):
            self.user_management_screen = UserManagementScreen()
            self.tabs.addTab(self.user_management_screen, "Users")
            self._refreshers.append(self.user_management_screen.refresh)

    def _build_menu(self):
        account_menu = self.menuBar().addMenu("Account")

        change_pw_action = QAction("Change Password", self)
        change_pw_action.triggered.connect(self.on_change_password)
        account_menu.addAction(change_pw_action)

        logout_action = QAction("Logout", self)
        logout_action.triggered.connect(self.on_logout)
        account_menu.addAction(logout_action)

    def on_change_password(self):
        ChangePasswordDialog(force=False, parent=self).exec()

    def on_logout(self):
        self.logout_requested = True
        self.close()

    def on_edit_purchase_invoice(self, invoice_id: int):
        self.purchase_screen.load_invoice_for_edit(invoice_id)
        self.tabs.setCurrentWidget(self.purchase_screen)

    def on_tab_changed(self):
        for refresh in self._refreshers:
            refresh()


def _configure_logging() -> None:
    """Send logs to a file next to the exe/package.

    The app uses ``logging`` throughout but never configured a handler, so
    messages went nowhere. A packaged windowed app has no console either, so a
    file log is the only way to diagnose a field issue.
    """
    log_dir = os.path.join(get_app_root(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(os.path.join(log_dir, "gemini_erp.log"), encoding="utf-8")],
    )


def _bootstrap() -> None:
    """Prepare the data directory and database before any screen loads.

    On a clean machine (packaged first run) there is no db and no documents/
    folder; the first screen would query missing tables and crash. Both are
    created here, idempotently, so an existing install is untouched. This also
    seeds roles + the default admin (ensure_roles_and_admin, via
    initialize_database).
    """
    os.makedirs(os.path.join(get_app_root(), "documents"), exist_ok=True)
    initialize_database()


def _login_flow() -> bool:
    """Show login, then a forced password change if required.

    Returns True when a user is logged in and ready for the main window, False
    if the user cancelled login or refused a required password change (the app
    should then exit).
    """
    login = LoginDialog()
    if login.exec() != QDialog.DialogCode.Accepted:
        return False

    user = SessionContext.get_user()
    if user is not None and user.must_change_password:
        change = ChangePasswordDialog(force=True)
        if change.exec() != QDialog.DialogCode.Accepted:
            SessionContext.clear()
            return False
    return True


def main():
    _configure_logging()
    try:
        _bootstrap()
        app = QApplication(sys.argv)
        # Loop so Logout returns to the login screen without restarting the app.
        while True:
            if not _login_flow():
                break
            window = MainWindow()
            window.show()
            app.exec()
            logged_out = window.logout_requested
            SessionContext.clear()
            if not logged_out:
                break
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        # Windowed builds have no console; record the crash so it isn't silent.
        logging.getLogger(__name__).exception("Fatal error during startup")
        raise


if __name__ == "__main__":
    main()
