"""Patch v1.1.0 UI smoke check (offscreen — no window is shown).

Drives the screens changed by the patch through their real widgets:
- startup: a fresh install migrates silently with no backup; an existing
  install with a pending migration is backed up, migrated and told once; a
  failed backup stops the app before anything touches the database
- MainWindow builds for Administrator, Accountant and Sales User; the Sales
  Log's Edit button exists only for Administrator / Accountant
- Purchase screen: Disc % + Special Discount drive the live totals panel via
  the service calculation, an invalid special discount is shown not crashed,
  and Save stores the discounts
- Billing screen edit mode: invoice no read-only, reason required, update goes
  through, the Sales Log shows the edit count, and Edit History lists it
- Credit notes screen: the type selector switches the GST fields, and a note
  saves through the form

ALWAYS runs on a throwaway SQLite file (GEMINI_DB_URL overridden below).

Run with: python check_patch_ui.py
"""

import os
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_DB_FILE = os.path.join(tempfile.mkdtemp(prefix="gemini_check_ui_"), "check_ui.db")
os.environ["GEMINI_DB_URL"] = f"sqlite:///{_DB_FILE}"

from datetime import date  # noqa: E402
from unittest import mock  # noqa: E402

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import main as app_main  # noqa: E402
from sqlalchemy import text  # noqa: E402

from database import engine, get_session  # noqa: E402
from models import Role, User  # noqa: E402
from services.auth_service import AuthService  # noqa: E402
from services.customer_service import CustomerService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.permissions import ROLE_ACCOUNTANT, ROLE_ADMINISTRATOR, ROLE_SALES_USER  # noqa: E402
from services.purchase_service import PurchaseService  # noqa: E402
from services.sales_service import SalesService  # noqa: E402
from services.session_context import SessionContext  # noqa: E402
from services.supplier_service import SupplierService  # noqa: E402


def _login_as(username):
    session = get_session()
    try:
        user = session.query(User).filter(User.username == username).one()
        _ = user.role.name  # load before the session closes
        session.expunge(user)
        session.expunge(user.role)
    finally:
        session.close()
    SessionContext.set_user(user)


def check_startup(app):
    shown = []
    info = mock.patch.object(QMessageBox, "information", side_effect=lambda *a: shown.append(a[2]))
    crit = mock.patch.object(QMessageBox, "critical", side_effect=lambda *a: shown.append("CRITICAL " + a[2]))
    with info, crit:
        # fresh install: nothing to back up, nothing to announce
        assert app_main._prepare_database(app) is True and shown == [], shown
        with engine.connect() as conn:
            versions = {v for (v,) in conn.execute(text("SELECT version FROM schema_migrations"))}
        assert versions == {"001", "002", "003"}, versions
        print("[1] fresh install: tables created, migrations recorded, no backup, no dialog OK")

        # an existing install with a pending migration: backup, migrate, announce
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM schema_migrations WHERE version = '003'"))
        assert app_main._prepare_database(app) is True
        assert len(shown) == 1 and "Applied: 003" in shown[0], shown
        backup = shown[0].rsplit("\n", 1)[-1]
        assert os.path.basename(backup).startswith("pre_patch_") and os.path.exists(backup)
        os.remove(backup)
        shown.clear()
        assert app_main._prepare_database(app) is True and shown == [], "next start: silent"
    print("[1b] existing install: backup + migrate + message once; next start silent OK")

    # A failed backup must stop before ANYTHING touches the database.
    svc = "services.migration_service.MigrationService"
    with mock.patch(f"{svc}.get_pending_migrations", return_value=["fake"]), \
         mock.patch(f"{svc}.has_existing_data", return_value=True), \
         mock.patch("services.backup_service.BackupService.auto_backup_before_migration",
                    side_effect=OSError("disk full")), \
         mock.patch.object(app_main, "_bootstrap") as bootstrap, \
         mock.patch(f"{svc}.run_pending") as run_pending, \
         mock.patch.object(QMessageBox, "critical", side_effect=lambda *a: shown.append(a[2])):
        assert app_main._prepare_database(app) is False
        bootstrap.assert_not_called()
        run_pending.assert_not_called()
        assert "NOT updated" in shown[-1]
    print("[1c] backup failure: app stops; neither create_all/seeding nor migrations ran OK")


def seed():
    session = get_session()
    try:
        auth = AuthService()
        for username, role_name in (("ui_admin", ROLE_ADMINISTRATOR), ("ui_acct", ROLE_ACCOUNTANT),
                                    ("ui_sales", ROLE_SALES_USER)):
            role = session.query(Role).filter(Role.name == role_name).one()
            auth.create_user(session, username, "Check@12345", username, role.id)
    finally:
        session.close()
    item = ItemService().add_item(code="UI-A", name="UI Item", gst_rate=18, opening_stock=100)
    customer = CustomerService().add_customer(name="UI Buyer", state="Andhra Pradesh")
    SupplierService().add_supplier(name="UI Supplier", state="Andhra Pradesh")
    invoice = SalesService().create_invoice("UI-INV-1", date.today(), customer.id,
                                            [{"item_id": item.id, "quantity": 10, "rate": 100}])
    return item, invoice


def check_roles():
    for username, can_edit in (("ui_admin", True), ("ui_acct", True), ("ui_sales", False)):
        _login_as(username)
        window = app_main.MainWindow()
        assert "1.1.0" in window.windowTitle()
        assert (window.sales_log_screen.edit_button is not None) == can_edit, username
        window.close()
    print("[2] MainWindow builds for all roles; version in title; Edit button only for "
          "Administrator / Accountant OK")


def check_purchase(window, item):
    screen = window.purchase_screen
    screen.refresh_lookups()
    screen.invoice_no_input.setText("UI-PUR-1")
    for i in range(screen.item_combo.count()):
        if screen.item_combo.itemData(i)["id"] == item.id:
            screen.item_combo.setCurrentIndex(i)
    screen.qty_input.setText("10")
    screen.rate_input.setText("100")
    screen.discount_input.setText("10")
    screen.on_add_line()
    assert len(screen.lines) == 1
    screen.special_discount_input.setText("100")
    assert screen.gross_label.text() == "Gross: 1000.00", screen.gross_label.text()
    assert screen.discount_label.text() == "Discount: 200.00"
    assert screen.taxable_label.text() == "Taxable: 800.00"
    assert screen.total_label.text() == "Net Total: 944.00"
    screen.special_discount_input.setText("5000")
    assert "cannot exceed" in screen.discount_error_label.text()
    screen.special_discount_input.setText("100")
    assert screen.discount_error_label.text() == ""
    with mock.patch.object(QMessageBox, "information"):
        screen.on_save_purchase()
    saved = PurchaseService().list_purchase_invoices()[0]
    assert saved["invoice_no"] == "UI-PUR-1" and saved["total"] == 944.0 and saved["total_discount"] == 200.0
    assert screen.special_discount_input.text() == ""
    print("[3] purchase screen: 10 x 100 less 10% less Rs 100 -> Gross 1000, Discount 200, "
          "Taxable 800, Net 944 live; bad special discount flagged; saved with discounts OK")


def check_billing_edit(window, invoice):
    window.on_edit_sales_invoice(invoice.id)
    billing = window.billing_screen
    assert billing.invoice_no_input.isReadOnly() and billing.save_button.text() == "Update Invoice"
    assert len(billing.lines) == 1
    billing.lines[0]["quantity"] = billing.lines[0]["quantity"] - 3  # 10 -> 7
    with mock.patch.object(QMessageBox, "warning") as warned:
        billing.on_save_invoice()  # no reason yet
        assert warned.called
    billing.edit_reason_input.setText("customer returned 3 before delivery")
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        billing.on_save_invoice()
    details = SalesService().get_invoice_details(invoice.id)
    assert details["edit_count"] == 1 and details["lines"][0]["quantity"] == 7.0
    assert not billing.invoice_no_input.isReadOnly() and billing.save_button.text() == "Save Invoice"
    window.sales_log_screen.refresh_invoices()
    assert window.sales_log_screen.table.item(0, 8).text() == "1"
    assert SalesService().get_edit_history(invoice.id)[0]["edited_by"] == "ui_admin"
    print("[4] billing edit mode: invoice no locked, reason required, edit saved (10 -> 7), "
          "Sales Log shows 1 edit, history records the user OK")


def check_credit_notes(window):
    screen = window.credit_notes_screen
    screen.refresh()
    assert not screen.taxable_input.isEnabled()
    screen.gst_radio.setChecked(True)
    assert screen.taxable_input.isEnabled() and "input tax credit" in screen.type_help.text()
    screen.commercial_radio.setChecked(True)
    assert not screen.cgst_input.isEnabled()
    screen.gst_radio.setChecked(True)
    screen.supplier_combo.setCurrentIndex(1)
    assert screen.linked_combo.count() == 2  # "none" + UI-PUR-1
    screen.note_no_input.setText("UI-CN-1")
    screen.taxable_input.setText("100")
    screen.cgst_input.setText("9")
    screen.sgst_input.setText("9")
    screen.total_input.setText("118")
    with mock.patch.object(QMessageBox, "information"):
        screen.on_save()
    assert screen.table.rowCount() == 1 and screen.table.item(0, 3).text() == "GST"
    print("[5] credit notes: type selector toggles GST fields + help text; GST note saved "
          "through the form and listed OK")


def main():
    assert "check_ui" in str(engine.url), f"refusing to run on {engine.url}"
    app = QApplication.instance() or QApplication([])
    check_startup(app)
    item, invoice = seed()
    check_roles()
    _login_as("ui_admin")
    window = app_main.MainWindow()
    check_purchase(window, item)
    check_billing_edit(window, invoice)
    check_credit_notes(window)
    window.close()
    print("\nAll patch v1.1.0 UI smoke checks passed.")


if __name__ == "__main__":
    main()
