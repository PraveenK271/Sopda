"""Application entry point."""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from ui.balance_sheet import BalanceSheetScreen
from ui.banking import BankingScreen
from ui.billing import BillingScreen
from ui.day_book import DayBookScreen
from ui.gst_reports import GstReportsScreen
from ui.gst_returns import GstReturnsScreen
from ui.item_master import ItemMasterScreen
from ui.ledger_view import LedgerViewScreen
from ui.ocr_purchase import DocumentHistoryScreen, OCRPurchaseScreen
from ui.outstanding import OutstandingScreen
from ui.profit_and_loss import ProfitAndLossScreen
from ui.purchase import PurchaseScreen
from ui.purchase_log import PurchaseLogScreen
from ui.sales_log import SalesLogScreen
from ui.trial_balance import TrialBalanceScreen


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gemini ERP")
        self.resize(1200, 800)

        self.item_master_screen = ItemMasterScreen()
        self.billing_screen = BillingScreen()
        self.purchase_screen = PurchaseScreen()
        self.sales_log_screen = SalesLogScreen()
        self.purchase_log_screen = PurchaseLogScreen()
        self.day_book_screen = DayBookScreen()
        self.ledger_view_screen = LedgerViewScreen()
        self.trial_balance_screen = TrialBalanceScreen()
        self.pl_screen = ProfitAndLossScreen()
        self.bs_screen = BalanceSheetScreen()
        self.outstanding_screen = OutstandingScreen()
        self.banking_screen = BankingScreen()
        self.gst_reports_screen = GstReportsScreen()
        self.gst_returns_screen = GstReturnsScreen()
        self.ocr_purchase_screen = OCRPurchaseScreen()
        self.document_history_screen = DocumentHistoryScreen()

        accounts_tabs = QTabWidget()
        accounts_tabs.addTab(self.day_book_screen, "Day Book")
        accounts_tabs.addTab(self.ledger_view_screen, "Ledger")
        accounts_tabs.addTab(self.trial_balance_screen, "Trial Balance")
        accounts_tabs.addTab(self.pl_screen, "P & L")
        accounts_tabs.addTab(self.bs_screen, "Balance Sheet")
        accounts_tabs.addTab(self.outstanding_screen, "Outstanding")

        gst_tabs = QTabWidget()
        gst_tabs.addTab(self.gst_reports_screen, "Registers/HSN")
        gst_tabs.addTab(self.gst_returns_screen, "Returns")

        documents_tabs = QTabWidget()
        documents_tabs.addTab(self.ocr_purchase_screen, "Scan Purchase Bill")
        documents_tabs.addTab(self.document_history_screen, "Document History")

        tabs = QTabWidget()
        tabs.addTab(self.item_master_screen, "Items")
        tabs.addTab(self.billing_screen, "Billing")
        tabs.addTab(self.purchase_screen, "Purchases")
        tabs.addTab(self.sales_log_screen, "Sales Log")
        tabs.addTab(self.purchase_log_screen, "Purchase Log")
        tabs.addTab(accounts_tabs, "Accounts")
        tabs.addTab(self.banking_screen, "Banking")
        tabs.addTab(gst_tabs, "GST")
        tabs.addTab(documents_tabs, "Documents")
        tabs.currentChanged.connect(self.on_tab_changed)
        self.setCentralWidget(tabs)

    def on_tab_changed(self):
        self.item_master_screen.refresh_items()
        self.billing_screen.refresh_lookups()
        self.purchase_screen.refresh_lookups()
        self.sales_log_screen.refresh_invoices()
        self.purchase_log_screen.refresh_invoices()
        self.ledger_view_screen.refresh_accounts()
        self.banking_screen.refresh_all()
        self.gst_reports_screen.refresh()
        self.gst_returns_screen.refresh()
        self.ocr_purchase_screen.refresh_lookups()
        self.document_history_screen.refresh()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
