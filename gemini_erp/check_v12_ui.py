"""Patch v1.2.0 UI smoke check (offscreen — no window is shown).

Drives the v1.2.0 screens through their real widgets:
- Sales Log buttons per role: Administrator gets Edit + Correct Number +
  Cancel; Accountant gets Edit only; Sales User gets none
- the Cancel dialog keeps OK disabled until the invoice number is typed back
  AND a reason is given; cancelling through the screen greys the row, marks it
  CANCELLED, disables Edit/Cancel for it, and "hide cancelled" removes it
- Correct Invoice Number through the screen
- Billing refuses to open a cancelled invoice for edit
- Settings: the GST filed-up-to date saves and the "not set" prompt hides
- Sales Register shows the CANCELLED section, excluded from the totals line;
  GSTR-1 screen lists the cancelled invoice; Cancelled Invoices and Sequence
  Check screens show it / report no gaps

ALWAYS runs on a throwaway SQLite file (GEMINI_DB_URL overridden below).

Run with: python check_v12_ui.py
"""

import os
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
_DB_FILE = os.path.join(tempfile.mkdtemp(prefix="gemini_check_v12ui_"), "check_v12ui.db")
os.environ["GEMINI_DB_URL"] = f"sqlite:///{_DB_FILE}"

from datetime import date, timedelta  # noqa: E402
from unittest import mock  # noqa: E402

from PySide6.QtCore import QDate  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

import main as app_main  # noqa: E402
from database import engine, get_session  # noqa: E402
from models import Role, User  # noqa: E402
from services.auth_service import AuthService  # noqa: E402
from services.customer_service import CustomerService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.permissions import ROLE_ACCOUNTANT, ROLE_ADMINISTRATOR, ROLE_SALES_USER  # noqa: E402
from services.sales_service import SalesService  # noqa: E402
from services.session_context import SessionContext  # noqa: E402
from services.settings_service import SettingsService  # noqa: E402
from ui.sales_log import CancelInvoiceDialog  # noqa: E402

TODAY = date.today()
YES, NO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


def _login_as(username):
    session = get_session()
    try:
        user = session.query(User).filter(User.username == username).one()
        _ = user.role.name
        session.expunge(user)
        session.expunge(user.role)
    finally:
        session.close()
    SessionContext.set_user(user)


def _row_of(screen, invoice_no):
    return next(i for i, inv in enumerate(screen.invoices) if inv["invoice_no"] == invoice_no)


def main():
    assert "check_v12ui" in str(engine.url), f"refusing to run on {engine.url}"
    app = QApplication.instance() or QApplication([])
    with mock.patch.object(QMessageBox, "information"):
        assert app_main._prepare_database(app) is True
    session = get_session()
    try:
        auth = AuthService()
        for username, role_name in (("v12_admin", ROLE_ADMINISTRATOR), ("v12_acct", ROLE_ACCOUNTANT),
                                    ("v12_sales", ROLE_SALES_USER)):
            role = session.query(Role).filter(Role.name == role_name).one()
            auth.create_user(session, username, "Check@12345", username, role.id)
    finally:
        session.close()
    item = ItemService().add_item(code="V12-A", name="V12 Item", gst_rate=18, opening_stock=100).id
    cust = CustomerService().add_customer(name="V12 Buyer", state="Andhra Pradesh").id
    line = [{"item_id": item, "quantity": 10, "rate": 100}]
    sales = SalesService()
    for number in ("V12-001", "V12-002", "V12-03"):
        sales.create_invoice(number, TODAY, cust, line, created_by="v12_admin")

    # [1] buttons per role
    expected = {"v12_admin": (True, True, True), "v12_acct": (True, False, False),
                "v12_sales": (False, False, False)}
    for username, (edit, correct, cancel) in expected.items():
        _login_as(username)
        window = app_main.MainWindow()
        log = window.sales_log_screen
        got = (log.edit_button is not None, log.correct_button is not None, log.cancel_button is not None)
        assert got == (edit, correct, cancel), (username, got)
        assert window.sales_log_tabs.count() == 3
        window.close()
    print("[1] Sales Log: Administrator = Edit + Correct Number + Cancel; Accountant = Edit; "
          "Sales User = none; Invoices / Cancelled / Sequence Check sub-tabs OK")

    _login_as("v12_admin")
    window = app_main.MainWindow()
    log = window.sales_log_screen

    # [2] cancel dialog gating
    details = sales.get_invoice_details(log.invoices[_row_of(log, "V12-002")]["id"])
    dialog = CancelInvoiceDialog(details)
    assert not dialog.ok_button.isEnabled()
    dialog.confirm_input.setText("V12-002")
    assert not dialog.ok_button.isEnabled(), "a reason is required too"
    dialog.reason_input.setPlainText("order withdrawn")
    assert dialog.ok_button.isEnabled()
    dialog.confirm_input.setText("V12-00")
    assert not dialog.ok_button.isEnabled(), "the number must match exactly"
    print("[2] Cancel dialog: OK enabled only with the exact number typed back AND a reason OK")

    # [3] cancel through the screen
    log.table.selectRow(_row_of(log, "V12-002"))
    with mock.patch.object(CancelInvoiceDialog, "exec", return_value=QDialog.DialogCode.Accepted), \
         mock.patch.object(CancelInvoiceDialog, "reason", return_value="order withdrawn"), \
         mock.patch.object(QMessageBox, "question", return_value=YES) as asked, \
         mock.patch("ui.sales_log.save_invoice_pdf") as saved_pdf:
        log.on_cancel_selected()
    assert saved_pdf.called, "after cancelling, the user is offered the CANCELLED PDF"
    assert any("not been filed" in str(c).lower() for c in asked.call_args_list), "GST-date-unset warning shown"
    row = _row_of(log, "V12-002")
    assert log.table.item(row, log.STATUS_COLUMN).text() == "CANCELLED"
    assert log.table.item(row, 7).font().strikeOut()
    log.table.selectRow(row)
    assert not log.cancel_button.isEnabled() and not log.edit_button.isEnabled()
    log.table.selectRow(_row_of(log, "V12-001"))
    assert log.cancel_button.isEnabled()
    assert ItemService().get_current_stock(item) == 80
    log.show_cancelled.setChecked(False)
    assert [inv["invoice_no"] for inv in log.invoices] == ["V12-03", "V12-001"]
    log.show_cancelled.setChecked(True)
    print("[3] cancel through the screen: GST-date warning confirmed, row struck through + "
          "CANCELLED, Edit/Cancel disabled on it, stock back to 80, PDF offered; "
          "'Show cancelled' hides it OK")

    # [4] Billing refuses a cancelled invoice
    cancelled_id = log.invoices[_row_of(log, "V12-002")]["id"]
    with mock.patch.object(QMessageBox, "warning") as warned:
        window.billing_screen.load_invoice_for_edit(cancelled_id)
    assert warned.called and window.billing_screen._editing_invoice_id is None
    print("[4] Billing refuses to open a cancelled invoice for edit OK")

    # [5] correct a number through the screen
    log.table.selectRow(_row_of(log, "V12-03"))
    from ui.sales_log import CorrectNumberDialog

    def fill(self):
        self.new_input.setText("V12-003")
        self.reason_input.setText("missing zero")
        return QDialog.DialogCode.Accepted

    # Yes to the GST-date-unset warning, No to "save the PDF now?".
    with mock.patch.object(CorrectNumberDialog, "exec", fill), \
         mock.patch.object(QMessageBox, "question", side_effect=[YES, NO]):
        log.on_correct_number()
    assert "V12-003" in [inv["invoice_no"] for inv in log.invoices]
    print("[5] Correct Invoice Number through the screen: V12-03 -> V12-003 OK")

    # [6] Settings GST filed-up-to date
    settings = window.settings_screen
    assert settings.gst_filed_prompt.isVisibleTo(settings)
    filed = TODAY - timedelta(days=40)
    settings.gst_filed_set.setChecked(True)
    settings.gst_filed_date.setDate(QDate(filed.year, filed.month, filed.day))
    with mock.patch.object(QMessageBox, "information"):
        settings.on_save_gst_filed()
    assert SettingsService().get_profile()["gst_filed_upto_date"] == filed
    assert not settings.gst_filed_prompt.isVisibleTo(settings)
    print(f"[6] Settings: GST filed-up-to saved as {filed}; 'not set' prompt hidden OK")

    # [7] reports
    gst = window.gst_reports_screen
    gst.date_from.setDate(QDate(TODAY.year, TODAY.month, 1))
    gst.date_to.setDate(QDate(TODAY.year, TODAY.month, TODAY.day))
    gst.view_combo.setCurrentText("Sales Register")
    gst.refresh()
    labels = [gst.table.item(r, 0).text() for r in range(gst.table.rowCount()) if gst.table.item(r, 0)]
    assert any("CANCELLED INVOICES" in t for t in labels), labels
    assert "Total: 2,360.00" in gst.totals_label.text(), gst.totals_label.text()
    gst.view_combo.setCurrentText("HSN Summary (Sales)")
    gst.refresh()
    assert gst.table.columnSpan(0, 0) == 1, "the heading span must not bleed into other views"
    returns = window.gst_returns_screen
    returns.date_from.setDate(QDate(TODAY.year, TODAY.month, 1))
    returns.refresh()
    assert returns.cancelled_table.rowCount() == 1 and returns.cancelled_table.item(0, 0).text() == "V12-002"
    window.cancelled_invoices_screen.refresh()
    assert window.cancelled_invoices_screen.table.rowCount() == 1
    window.sequence_check_screen.refresh()
    assert "No gaps" in window.sequence_check_screen.verdict.text()
    print("[7] Sales Register: CANCELLED section under 2 active invoices (total 2,360); span "
          "cleared on view change; GSTR-1 screen lists V12-002; Cancelled Invoices shows 1; "
          "Sequence Check: no gaps OK")

    window.close()
    print("\nAll patch v1.2.0 UI smoke checks passed.")


if __name__ == "__main__":
    main()
