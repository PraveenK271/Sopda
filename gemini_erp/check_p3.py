"""Patch v1.1.0 P3 check: edit an existing sales invoice (reverse, then re-post).

Covers the full test list in INSTRUCTIONS_PATCH_V1_1.md, P3:
- the 8-row stock scenario matrix (Item A starts at 100, Item B at 50), incl.
  row 3 (line removed), row 6 (same item on two lines — catches grouping the
  reversal by item) and row 8 (the second-edit trap — 94, not 84 or 104)
- accounting: the invoice's journals net to the new amounts, the Trial Balance
  balances, originals still exist, reversals carry the ORIGINAL invoice date,
  and an in-state -> out-of-state customer change moves CGST+SGST to IGST
- guards that must raise, warnings that must warn but not block
- audit rows, and the all-or-nothing rollback test (byte-for-byte)

ALWAYS runs on a throwaway SQLite file (GEMINI_DB_URL overridden below).

Run with: python check_p3.py
"""

import os
import tempfile

_DB_FILE = os.path.join(tempfile.mkdtemp(prefix="gemini_check_p3_"), "check_p3.db")
os.environ["GEMINI_DB_URL"] = f"sqlite:///{_DB_FILE}"

import itertools  # noqa: E402
from datetime import date, timedelta  # noqa: E402

from sqlalchemy import false, text  # noqa: E402

from create_db import initialize_database  # noqa: E402
from database import engine, get_session  # noqa: E402
from models import (  # noqa: E402
    Item,
    JournalEntry,
    LedgerAccount,
    Role,
    SalesInvoice,
    StockTransaction,
)
from services.accounting_service import AccountingService  # noqa: E402
from services.auth_service import AuthService  # noqa: E402
from services.banking_service import BankingService  # noqa: E402
from services.customer_service import CustomerService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.migration_service import MigrationService  # noqa: E402
from services.period_lock_service import PeriodLockService  # noqa: E402
from services.permissions import ROLE_ACCOUNTANT, ROLE_ADMINISTRATOR, ROLE_SALES_USER  # noqa: E402
from services.sales_service import (  # noqa: E402
    REF_SALE,
    REF_SALE_EDIT_REVERSAL,
    InvoiceEditPermissionError,
    SalesService,
)

TODAY = date.today()
PREV_MONTH_DAY = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=15)
ADMIN, ACCOUNTANT, SALES_USER = "chk_admin", "chk_accountant", "chk_sales"
_seq = itertools.count(1)

sales = SalesService()
items_svc = ItemService()


# ----- fixtures ------------------------------------------------------------

def _setup():
    assert "check_p3" in str(engine.url), f"refusing to run on {engine.url}"
    initialize_database()
    session = get_session()
    try:
        MigrationService().run_pending(session, applied_by="check_p3")
        auth = AuthService()
        for username, role_name in (
            (ADMIN, ROLE_ADMINISTRATOR), (ACCOUNTANT, ROLE_ACCOUNTANT), (SALES_USER, ROLE_SALES_USER),
        ):
            role = session.query(Role).filter(Role.name == role_name).one()
            auth.create_user(session, username, "Check@12345", username, role.id)
    finally:
        session.close()
    customers = CustomerService()
    return (
        customers.add_customer(name="P3 AP Buyer", state="Andhra Pradesh").id,
        customers.add_customer(name="P3 KA Buyer", state="Karnataka").id,
    )


def _items():
    """A fresh Item A (stock 100) and Item B (stock 50) for each scenario."""
    n = next(_seq)
    a = items_svc.add_item(code=f"P3-A{n}", name="Item A", gst_rate=18, opening_stock=100).id
    b = items_svc.add_item(code=f"P3-B{n}", name="Item B", gst_rate=5, opening_stock=50).id
    return a, b


def _line(item_id, qty, rate=100):
    return {"item_id": item_id, "quantity": qty, "rate": rate}


def _invoice(customer_id, lines, on=TODAY):
    return sales.create_invoice(f"P3-INV-{next(_seq)}", on, customer_id, lines, created_by=ADMIN).id


def _edit(invoice_id, customer_id, lines, user=ADMIN, reason="check_p3 correction", on=None, **extra):
    data = {"customer_id": customer_id, "lines": lines, **extra}
    if on is not None:
        data["date"] = on
    return sales.update_invoice(invoice_id, data, reason, user)


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


def _journal_net(invoice_id) -> dict:
    """Net Dr-Cr per account code over every journal of this invoice (the
    original, its reversals and the re-posts). Party ledgers keyed by id."""
    session = get_session()
    try:
        entries = (
            session.query(JournalEntry)
            .filter(
                JournalEntry.reference_id == invoice_id,
                JournalEntry.reference_type.in_([REF_SALE, REF_SALE_EDIT_REVERSAL]),
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


def _assert_books(invoice_id, customer_id):
    session = get_session()
    try:
        inv = session.get(SalesInvoice, invoice_id)
        expected = {f"party:{customer_id}": round(float(inv.total), 2),
                    "SALES": -round(float(inv.taxable_amount), 2)}
        for head, code in (("cgst", "CGST_OUTPUT"), ("sgst", "SGST_OUTPUT"), ("igst", "IGST_OUTPUT")):
            if float(getattr(inv, head)):
                expected[code] = -round(float(getattr(inv, head)), 2)
    finally:
        session.close()
    assert _journal_net(invoice_id) == expected, (_journal_net(invoice_id), expected)
    assert _tb_balances(), "trial balance must still balance"


def _rows(model, invoice_id):
    session = get_session()
    try:
        return (
            session.query(model)
            .filter(model.reference_id == invoice_id)
            .order_by(model.id)
            .all()
        )
    finally:
        session.close()


def _dump() -> dict:
    """Every row of every table an edit touches — for the rollback test."""
    tables = ["stock_transactions", "journal_entries", "journal_entry_lines", "sales_invoices",
              "sales_invoice_items", "sales_invoice_audit"]
    with engine.connect() as conn:
        return {t: conn.execute(text(f"SELECT * FROM {t} ORDER BY id")).fetchall() for t in tables}


# ----- the checks ------------------------------------------------------------

def stock_matrix(ap):
    results = []

    def row(n, orig, edits, expect_a, expect_b):
        a, b = _items()
        lines = lambda spec: [_line({"A": a, "B": b}[k], q, r) for k, q, r in spec]  # noqa: E731
        inv = _invoice(ap, lines(orig))
        for spec in edits:
            _edit(inv, ap, lines(spec))
            _assert_books(inv, ap)
        got_a, got_b = _stock(a), _stock(b)
        assert got_a == expect_a, f"row {n}: stock A {got_a} != {expect_a}"
        if expect_b is not None:
            assert got_b == expect_b, f"row {n}: stock B {got_b} != {expect_b}"
        results.append(f"row {n}: A={got_a:g}" + (f" B={got_b:g}" if expect_b is not None else ""))
        return inv, a

    row(1, [("A", 10, 100)], [[("A", 8, 100)]], 92, None)
    row(2, [("A", 10, 100)], [[("A", 15, 100)]], 85, None)
    row(3, [("A", 10, 100), ("B", 5, 100)], [[("A", 10, 100)]], 90, 50)
    row(4, [("A", 10, 100)], [[("A", 10, 100), ("B", 5, 100)]], 90, 45)
    row(5, [("A", 10, 100)], [[("B", 10, 100)]], 100, 40)
    row(6, [("A", 5, 100), ("A", 3, 90)], [[("A", 5, 100)]], 95, None)
    inv7, _ = row(7, [("A", 10, 100)], [[("A", 10, 120)]], 90, None)
    inv8, _ = row(8, [("A", 10, 100)], [[("A", 8, 100)], [("A", 6, 100)]], 94, None)

    session = get_session()
    try:
        assert float(session.get(SalesInvoice, inv7).taxable_amount) == 1200.0
    finally:
        session.close()
    print("[1] stock matrix: " + "; ".join(results) + " OK")
    return inv8


def originals_survive(inv8):
    # Row 8 had OUT 10, then IN 10 + OUT 8, then IN 8 + OUT 6.
    stock = _rows(StockTransaction, inv8)
    kinds = [(s.type, float(s.quantity), s.reference_type, s.is_reversed, s.is_deleted) for s in stock]
    assert kinds == [
        ("OUT", 10.0, REF_SALE, True, False),
        ("IN", 10.0, REF_SALE_EDIT_REVERSAL, False, False),
        ("OUT", 8.0, REF_SALE, True, False),
        ("IN", 8.0, REF_SALE_EDIT_REVERSAL, False, False),
        ("OUT", 6.0, REF_SALE, False, False),
    ], kinds
    journals = _rows(JournalEntry, inv8)
    assert [(j.reference_type, j.is_reversed, j.is_deleted) for j in journals] == [
        (REF_SALE, True, False), (REF_SALE_EDIT_REVERSAL, False, False),
        (REF_SALE, True, False), (REF_SALE_EDIT_REVERSAL, False, False),
        (REF_SALE, False, False),
    ]
    print("[2] after two edits the original OUT 10 and its journal still exist (flagged "
          "is_reversed, not deleted); only the latest OUT/journal is live OK")


def reversal_dates(ap):
    a, _ = _items()
    inv = _invoice(ap, [_line(a, 10)], on=PREV_MONTH_DAY)
    warnings = sales.preview_invoice_edit(inv, {"customer_id": ap, "lines": [_line(a, 7)]}, "fix", ADMIN)
    assert any("earlier month" in w for w in warnings), warnings
    edited = _edit(inv, ap, [_line(a, 7)])  # warned, NOT blocked
    assert any("earlier month" in w for w in edited.edit_warnings)
    reversals = [s for s in _rows(StockTransaction, inv) if s.reference_type == REF_SALE_EDIT_REVERSAL]
    rev_journals = [j for j in _rows(JournalEntry, inv) if j.reference_type == REF_SALE_EDIT_REVERSAL]
    assert reversals and all(s.date == PREV_MONTH_DAY for s in reversals)
    assert rev_journals and all(j.date == PREV_MONTH_DAY for j in rev_journals)
    assert _stock(a) == 93
    _assert_books(inv, ap)
    print(f"[3] invoice dated {PREV_MONTH_DAY}: edit warned (earlier month) but went through; "
          f"reversing stock rows and journal dated {PREV_MONTH_DAY}, not today OK")


def customer_change(ap, ka):
    a, _ = _items()
    inv = _invoice(ap, [_line(a, 10)])
    session = get_session()
    try:
        before = session.get(SalesInvoice, inv)
        assert float(before.cgst) > 0 and float(before.igst) == 0
    finally:
        session.close()
    warnings = sales.preview_invoice_edit(inv, {"customer_id": ka, "lines": [_line(a, 10)]}, "x", ADMIN)
    assert any("customer is changing" in w for w in warnings), warnings
    _edit(inv, ka, [_line(a, 10)])
    net = _journal_net(inv)
    assert f"party:{ap}" not in net, "original customer must be credited back to zero on this invoice"
    session = get_session()
    try:
        after = session.get(SalesInvoice, inv)
        assert after.customer_id == ka
        assert float(after.cgst) == 0 and float(after.sgst) == 0 and float(after.igst) == 180.0
        assert net[f"party:{ka}"] == float(after.total) == 1180.0
    finally:
        session.close()
    assert "CGST_OUTPUT" not in net and net["IGST_OUTPUT"] == -180.0
    _assert_books(inv, ka)
    print("[4] AP -> KA customer change: warned; AP ledger nets to 0, KA debited 1180; "
          "CGST+SGST became IGST 180 OK")


def guards(ap):
    a, _ = _items()
    inv = _invoice(ap, [_line(a, 10)])
    ok = [_line(a, 9)]
    _raises(lambda: _edit(inv, ap, []), ValueError, "at least one item")
    _raises(lambda: _edit(inv, ap, ok, invoice_no="SOMETHING-ELSE"), ValueError, "cannot be changed")
    other_month = TODAY.replace(day=1) - timedelta(days=1)
    _raises(lambda: _edit(inv, ap, ok, on=other_month), ValueError, "same month")
    _raises(lambda: _edit(inv, ap, ok, reason="   "), ValueError, "reason")
    _raises(lambda: _edit(inv, ap, ok, user=SALES_USER), InvoiceEditPermissionError, "Administrator or Accountant")
    _raises(lambda: _edit(inv, ap, ok, user="nobody"), InvoiceEditPermissionError, "Administrator or Accountant")
    # the same number passed explicitly, and a date move within the month, are fine
    same_month_day = TODAY.replace(day=1 if TODAY.day != 1 else 2)
    _edit(inv, ap, ok, user=ACCOUNTANT, invoice_no=f" {sales.get_invoice_details(inv)['invoice_no']} ",
          on=same_month_day)
    assert _stock(a) == 91

    # locked period: blocked
    b, _ = _items()
    locked_inv = _invoice(ap, [_line(b, 10)], on=PREV_MONTH_DAY)
    lock = PeriodLockService()
    lock.lock(PREV_MONTH_DAY, "check_p3", "check")
    try:
        _raises(lambda: _edit(locked_inv, ap, [_line(b, 5)]), ValueError, "locked")
    finally:
        lock.unlock("check_p3", "check done")
    assert _stock(b) == 90

    # oversell: the app's policy on a normal sale is "allow but warn" -> same here
    c, _ = _items()
    inv_c = _invoice(ap, [_line(c, 10)])
    exact = _edit(inv_c, ap, [_line(c, 100)])  # 10 come back, 100 go out -> exactly 0
    assert _stock(c) == 0 and exact.stock_warnings == [], "returning stock must be counted once"
    over = _edit(inv_c, ap, [_line(c, 101)])
    assert _stock(c) == -1 and over.stock_warnings, "oversell must warn, like a normal sale"
    print("[5] guards raise: no lines, changed invoice_no, other month, empty reason, "
          "Sales User / unknown user, locked period. Oversell follows the sale policy "
          "(warn, not block) and counts returning stock once OK")


def receipt_warning(ap):
    a, _ = _items()
    customer = CustomerService().add_customer(name="P3 Payer", state="Andhra Pradesh").id
    inv = _invoice(customer, [_line(a, 10)])
    BankingService().record_receipt(TODAY, customer, 500, "CASH", created_by=ADMIN)
    warnings = sales.preview_invoice_edit(inv, {"customer_id": customer, "lines": [_line(a, 2)]}, "x", ADMIN)
    assert any("Receipts of 500.00" in w for w in warnings), warnings
    edited = _edit(inv, customer, [_line(a, 2)])
    assert _stock(a) == 98 and any("Receipts" in w for w in edited.edit_warnings)
    print("[6] receipt recorded: warned (not blocked), edit applied OK")


def deleted_item(ap):
    a, _ = _items()
    gone, _ = _items()
    inv = _invoice(ap, [_line(gone, 10)])
    session = get_session()
    try:
        session.get(Item, gone).is_deleted = True
        session.commit()
    finally:
        session.close()
    _raises(lambda: _edit(inv, ap, [_line(gone, 5)]), ValueError, "not found")
    _edit(inv, ap, [_line(a, 4)])
    assert _stock(gone) == 100 and _stock(a) == 96
    print("[7] item soft-deleted after the sale still gets its reversing IN; it cannot "
          "be on the NEW lines OK")


def audit_and_rollback(ap, inv8):
    history = sales.get_edit_history(inv8)
    details = sales.get_invoice_details(inv8)
    assert len(history) == details["edit_count"] == 2
    assert all(h["before"] and h["after"] and h["reason"] and h["edited_by"] == ADMIN for h in history)
    assert history[0]["before"]["lines"][0]["quantity"].startswith("10")
    assert history[1]["after"]["lines"][0]["quantity"].startswith("6")
    assert len(details["lines"]) == 1 and details["lines"][0]["quantity"] == 6.0

    a, _ = _items()
    inv = _invoice(ap, [_line(a, 10)])
    _edit(inv, ap, [_line(a, 8)])  # a prior edit, so flags/edit_count are non-trivial
    snapshot = _dump()
    # Fails at step 7 — AFTER the reversal rows/journal have been written and
    # flushed, and the is_reversed flags flipped.
    _raises(lambda: _edit(inv, ap, [_line(a, 5), _line(999999, 1)]), ValueError, "not found")
    assert _dump() == snapshot, "a failed edit must leave every row exactly as it was"
    assert _stock(a) == 92 and sales.get_invoice_details(inv)["edit_count"] == 1
    print("[8] audit: one row per edit, snapshots populated, edit_count matches. Rollback: "
          "failure mid-edit left stock, journals, flags, invoice and edit_count byte-for-byte "
          "unchanged OK")


def main():
    ap, ka = _setup()
    inv8 = stock_matrix(ap)
    originals_survive(inv8)
    reversal_dates(ap)
    customer_change(ap, ka)
    guards(ap)
    receipt_warning(ap)
    deleted_item(ap)
    audit_and_rollback(ap, inv8)
    assert _tb_balances()
    print("\nAll P3 (sales invoice edit) checks passed.")


if __name__ == "__main__":
    main()
