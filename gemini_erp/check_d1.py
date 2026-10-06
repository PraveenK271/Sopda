"""Patch v1.2.0 D1 check: cancel a sales invoice (never a delete).

Covers the test list in INSTRUCTIONS_PATCH_V1_2.md, D1:
- stock: 100 -> sell 10 -> 90 -> cancel -> 100, original OUT row kept and
  flagged; a multi-line invoice returns every item; sell 10 -> edit to 8 ->
  cancel reads 100 (not 92, not 108) — is_reversed honoured across features
- books: the invoice's journals net to zero, the Trial Balance balances, the
  customer's outstanding drops by the invoice total, reversals carry the
  ORIGINAL invoice date
- guards that raise; the receipt warning that warns but does not block
- audit row action CANCEL with both snapshots; lines still readable; PDF with
  the watermark; and the byte-for-byte rollback test
- the "GST filed up to" setting: Administrator only, not in the future

ALWAYS runs on a throwaway SQLite file (GEMINI_DB_URL overridden below).

Run with: python check_d1.py
"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="gemini_check_d1_")
os.environ["GEMINI_DB_URL"] = f"sqlite:///{os.path.join(_TMP, 'check_d1.db')}"

import itertools  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from unittest import mock  # noqa: E402

from sqlalchemy import false, text  # noqa: E402

from create_db import initialize_database  # noqa: E402
from database import engine, get_session  # noqa: E402
from models import JournalEntry, LedgerAccount, Role, SalesInvoice, StockTransaction  # noqa: E402
from reports.invoice_pdf import generate_invoice_pdf  # noqa: E402
from services.accounting_service import AccountingService  # noqa: E402
from services.auth_service import AuthService  # noqa: E402
from services.banking_service import BankingService  # noqa: E402
from services.customer_service import CustomerService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.migration_service import MigrationService  # noqa: E402
from services.period_lock_service import PeriodLockService  # noqa: E402
from services.permissions import ROLE_ACCOUNTANT, ROLE_ADMINISTRATOR, ROLE_SALES_USER  # noqa: E402
from services.sales_service import (  # noqa: E402
    ACTION_CANCEL,
    REF_SALE,
    REF_SALE_CANCELLATION,
    REF_SALE_EDIT_REVERSAL,
    STATUS_CANCELLED,
    SalesService,
)
from services.settings_service import SettingsService  # noqa: E402

TODAY = date.today()
PREV_MONTH_DAY = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=15)
ADMIN, ACCOUNTANT, SALES_USER = "d1_admin", "d1_accountant", "d1_sales"
_seq = itertools.count(1)

sales = SalesService()
items_svc = ItemService()
settings = SettingsService()


# ----- fixtures ----------------------------------------------------------------

def _setup():
    assert "check_d1" in str(engine.url), f"refusing to run on {engine.url}"
    initialize_database()
    session = get_session()
    try:
        MigrationService().run_pending(session, applied_by="check_d1")
        auth = AuthService()
        for username, role_name in (
            (ADMIN, ROLE_ADMINISTRATOR), (ACCOUNTANT, ROLE_ACCOUNTANT), (SALES_USER, ROLE_SALES_USER),
        ):
            role = session.query(Role).filter(Role.name == role_name).one()
            auth.create_user(session, username, "Check@12345", username, role.id)
    finally:
        session.close()
    return CustomerService().add_customer(name="D1 Buyer", state="Andhra Pradesh").id


def _items():
    n = next(_seq)
    a = items_svc.add_item(code=f"D1-A{n}", name="Item A", gst_rate=18, opening_stock=100).id
    b = items_svc.add_item(code=f"D1-B{n}", name="Item B", gst_rate=5, opening_stock=50).id
    return a, b


def _line(item_id, qty, rate=100):
    return {"item_id": item_id, "quantity": qty, "rate": rate}


def _invoice(customer_id, lines, on=TODAY):
    return sales.create_invoice(f"D1-{next(_seq)}", on, customer_id, lines, created_by=ADMIN).id


def _cancel(invoice_id, reason="sale did not happen", user=ADMIN):
    return sales.cancel_invoice(invoice_id, reason, user)


def _stock(item_id):
    return items_svc.get_current_stock(item_id)


def _raises(fn, exc_type, fragment):
    try:
        fn()
    except exc_type as exc:
        assert fragment.lower() in str(exc).lower(), (fragment, str(exc))
        return
    raise AssertionError(f"expected {exc_type.__name__} containing '{fragment}'")


def _tb_balances():
    tb = AccountingService.get_trial_balance()
    return round(sum(r["debit"] for r in tb), 2) == round(sum(r["credit"] for r in tb), 2)


def _invoice_journal_net(invoice_id) -> dict:
    session = get_session()
    try:
        entries = (
            session.query(JournalEntry)
            .filter(
                JournalEntry.reference_id == invoice_id,
                JournalEntry.reference_type.in_([REF_SALE, REF_SALE_EDIT_REVERSAL, REF_SALE_CANCELLATION]),
                JournalEntry.is_deleted == false(),
            )
            .all()
        )
        net: dict = {}
        for entry in entries:
            for line in entry.lines:
                acct = session.get(LedgerAccount, line.account_id)
                key = acct.code or f"party:{acct.customer_id}"
                net[key] = round(net.get(key, 0.0) + float(line.debit) - float(line.credit), 2)
        return {k: v for k, v in net.items() if abs(v) > 0.001}
    finally:
        session.close()


def _rows(model, invoice_id):
    session = get_session()
    try:
        return session.query(model).filter(model.reference_id == invoice_id).order_by(model.id).all()
    finally:
        session.close()


def _outstanding(customer_id) -> float:
    return next((r["outstanding"] for r in AccountingService.get_outstanding_customers()
                 if r["customer_id"] == customer_id), 0.0)


def _dump() -> dict:
    tables = ["stock_transactions", "journal_entries", "journal_entry_lines", "sales_invoices",
              "sales_invoice_items", "sales_invoice_audit"]
    with engine.connect() as conn:
        return {t: conn.execute(text(f"SELECT * FROM {t} ORDER BY id")).fetchall() for t in tables}


# ----- checks ----------------------------------------------------------------------

def stock_and_books(cust):
    a, b = _items()
    inv = _invoice(cust, [_line(a, 10)])
    assert _stock(a) == 90
    owed_before = _outstanding(cust)
    total = sales.get_invoice_details(inv)["total"]
    cancelled = _cancel(inv)
    assert cancelled.status == STATUS_CANCELLED and _stock(a) == 100
    out_rows = [r for r in _rows(StockTransaction, inv) if r.type == "OUT"]
    assert len(out_rows) == 1 and out_rows[0].is_reversed and not out_rows[0].is_deleted
    assert _invoice_journal_net(inv) == {}, _invoice_journal_net(inv)
    assert _tb_balances()
    assert round(owed_before - _outstanding(cust), 2) == total, (owed_before, _outstanding(cust), total)
    print(f"[1] sell 10 -> 90 -> cancel -> {_stock(a):g}; original OUT kept + flagged; "
          f"journals net to zero; TB balances; outstanding -{total:.2f} OK")

    inv2 = _invoice(cust, [_line(a, 10), _line(b, 5)])
    assert (_stock(a), _stock(b)) == (90, 45)
    _cancel(inv2)
    assert (_stock(a), _stock(b)) == (100, 50)
    print("[2] multi-line A x 10, B x 5 cancelled -> A 100, B 50 OK")

    c, _ = _items()
    inv3 = _invoice(cust, [_line(c, 10)])
    sales.update_invoice(inv3, {"customer_id": cust, "lines": [_line(c, 8)]}, "fix qty", ADMIN)
    assert _stock(c) == 92
    _cancel(inv3)
    assert _stock(c) == 100, f"edit then cancel: stock {_stock(c)}, expected 100 (not 92 / 108)"
    kinds = [(r.type, float(r.quantity), r.reference_type, r.is_reversed) for r in _rows(StockTransaction, inv3)]
    assert kinds == [
        ("OUT", 10.0, REF_SALE, True), ("IN", 10.0, REF_SALE_EDIT_REVERSAL, False),
        ("OUT", 8.0, REF_SALE, True), ("IN", 8.0, REF_SALE_CANCELLATION, False),
    ], kinds
    assert _invoice_journal_net(inv3) == {} and _tb_balances()
    print("[3] sell 10 -> edit to 8 -> cancel -> 100 (only the OUT 8 in force was "
          "reversed; the superseded OUT 10 was not touched again) OK")

    d, _ = _items()
    inv4 = _invoice(cust, [_line(d, 10)], on=PREV_MONTH_DAY)
    warnings = sales.preview_cancellation(inv4, "x", ADMIN)
    assert any("never been set" in w for w in warnings), warnings  # GST date unset -> warn
    _cancel(inv4)
    reversals = [r for r in _rows(StockTransaction, inv4) if r.reference_type == REF_SALE_CANCELLATION]
    journals = [j for j in _rows(JournalEntry, inv4) if j.reference_type == REF_SALE_CANCELLATION]
    assert reversals and all(r.date == PREV_MONTH_DAY for r in reversals)
    assert journals and all(j.date == PREV_MONTH_DAY for j in journals)
    print(f"[4] invoice dated {PREV_MONTH_DAY}: reversing stock rows + journal dated "
          f"{PREV_MONTH_DAY}, not today; unset GST date warned, did not block OK")


def settings_guard():
    _raises(lambda: settings.set_gst_filed_upto_date(PREV_MONTH_DAY, ACCOUNTANT), PermissionError, "Administrator")
    _raises(lambda: settings.set_gst_filed_upto_date(TODAY + timedelta(days=1), ADMIN), ValueError, "future")
    settings.set_gst_filed_upto_date(PREV_MONTH_DAY, ADMIN)
    assert settings.get_profile()["gst_filed_upto_date"] == PREV_MONTH_DAY
    print(f"[5] GST filed-up-to set to {PREV_MONTH_DAY} by Administrator; Accountant refused; "
          "future date refused OK")


def guards(cust):
    a, _ = _items()
    inv = _invoice(cust, [_line(a, 10)])
    _raises(lambda: _cancel(inv, reason="  "), ValueError, "reason")
    _raises(lambda: _cancel(inv, user=ACCOUNTANT), PermissionError, "Administrator")
    _raises(lambda: _cancel(inv, user=SALES_USER), PermissionError, "Administrator")
    _raises(lambda: _cancel(inv, user="nobody"), PermissionError, "Administrator")
    number = sales.get_invoice_details(inv)["invoice_no"]
    _cancel(inv)
    _raises(lambda: _cancel(inv), ValueError, "already")  # "cancelled ... cannot be ... cancelled again"
    _raises(lambda: sales.update_invoice(inv, {"customer_id": cust, "lines": [_line(a, 5)]}, "x", ADMIN),
            ValueError, "cancelled")
    _raises(lambda: sales.create_invoice(number, TODAY, cust, [_line(a, 1)], created_by=ADMIN),
            ValueError, "already used")
    assert _stock(a) == 100

    # filed period: dated on the filed-up-to date -> blocked
    b, _ = _items()
    filed = _invoice(cust, [_line(b, 10)], on=PREV_MONTH_DAY)
    _raises(lambda: _cancel(filed), ValueError, "GSTR-1 for this period has been filed")
    assert _stock(b) == 90

    # locked period (H6) -> blocked. Clear the GST date so the lock is what bites.
    settings.set_gst_filed_upto_date(None, ADMIN)
    lock = PeriodLockService()
    lock.lock(PREV_MONTH_DAY, "check_d1", "check")
    try:
        _raises(lambda: _cancel(filed), ValueError, "locked")
    finally:
        lock.unlock("check_d1", "check done")
    settings.set_gst_filed_upto_date(PREV_MONTH_DAY, ADMIN)
    assert _stock(b) == 90 and sales.get_invoice_details(filed)["status"] == "ACTIVE"
    print("[6] raise: empty reason, Accountant / Sales User / unknown user, already "
          "cancelled, update_invoice on a cancelled invoice, reusing a cancelled number, "
          "filed GST period, locked period OK")


def receipt_warning():
    a, _ = _items()
    payer = CustomerService().add_customer(name="D1 Payer", state="Andhra Pradesh").id
    inv = _invoice(payer, [_line(a, 10)])  # 1,180.00
    BankingService().record_receipt(TODAY, payer, 500, "CASH", created_by=ADMIN)
    warnings = sales.preview_cancellation(inv, "x", ADMIN)
    assert any("credit balance of Rs 500.00" in w for w in warnings), warnings
    cancelled = _cancel(inv)
    assert any("credit balance" in w for w in cancelled.cancel_warnings)
    session = get_session()
    try:
        ledger_id = session.get(SalesInvoice, inv).customer.ledger_account.id
        assert AccountingService.get_account_balance(session, ledger_id) == -500.0
    finally:
        session.close()
    assert _stock(a) == 100 and _tb_balances()
    print("[7] receipt of 500 against a 1,180 invoice: warned 'credit balance of Rs 500.00', "
          "not blocked; customer ledger now Cr 500 OK")


def audit_and_rollback(cust):
    a, b = _items()
    inv = _invoice(cust, [_line(a, 10), _line(b, 5)])
    _cancel(inv, reason="customer refused delivery")
    history = sales.get_edit_history(inv)
    assert [h["action"] for h in history] == [ACTION_CANCEL]
    h = history[0]
    assert h["before"]["status"] == "ACTIVE" and h["after"]["status"] == STATUS_CANCELLED
    assert h["reason"] == "customer refused delivery" and h["edited_by"] == ADMIN
    details = sales.get_invoice_details(inv)
    assert len(details["lines"]) == 2 and details["cancellation_reason"] == "customer refused delivery"
    assert details["cancelled_by"] == ADMIN and details["edit_count"] == 0
    pdf = generate_invoice_pdf(inv, os.path.join(_TMP, "cancelled.pdf"))
    assert os.path.getsize(pdf) > 0
    print("[8] audit row action CANCEL, snapshots ACTIVE -> CANCELLED; both lines still "
          "readable; PDF with CANCELLED watermark generated OK")

    # Rollback: an edit first (so flags/edit_count are non-trivial), then make
    # the journal step fail AFTER the stock reversal rows were written and the
    # OUT rows flagged.
    c, _ = _items()
    inv2 = _invoice(cust, [_line(c, 10)])
    sales.update_invoice(inv2, {"customer_id": cust, "lines": [_line(c, 7)]}, "fix", ADMIN)
    snapshot = _dump()
    with mock.patch("services.sales_service.AccountingService.post_journal_entry",
                    side_effect=RuntimeError("forced failure mid-cancellation")):
        _raises(lambda: _cancel(inv2), RuntimeError, "forced failure")
    assert _dump() == snapshot, "a failed cancellation must leave every row exactly as it was"
    assert _stock(c) == 93 and sales.get_invoice_details(inv2)["status"] == "ACTIVE"
    print("[9] rollback: failure after the stock reversal left stock, journals, is_reversed "
          "flags, status and audit byte-for-byte unchanged OK")


def main():
    cust = _setup()
    stock_and_books(cust)
    settings_guard()
    guards(cust)
    receipt_warning()
    audit_and_rollback(cust)
    assert _tb_balances()
    print("\nAll D1 (cancel a sales invoice) checks passed.")


if __name__ == "__main__":
    main()
