"""Patch v1.1.0 P5 check: the UPGRADE PATH on a real pre-patch database.

Takes a COPY of a pre-patch database (default: gemini_erp.db next to this
file, or the path given as the first argument), points the app at the copy,
runs the real startup sequence (main._prepare_database), and proves:
- the automatic backup was written and is byte-identical to the pre-patch db
- every pre-existing row of every pre-existing table is unchanged in every
  pre-existing column (nothing destroyed, altered or orphaned); new columns
  hold their neutral defaults
- every purchase invoice total, sales total, item stock figure and the Trial
  Balance are identical before and after (Rule B)
- the three new features then work on that same database, with the books
  balanced after each

The original database file is never opened for writing.

Run with: python check_upgrade_path.py [path\\to\\pre_patch.db]
"""

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile

_SOURCE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "gemini_erp.db"))
_TMP = tempfile.mkdtemp(prefix="gemini_upgrade_")
_COPY = os.path.join(_TMP, "upgrade_copy.db")
shutil.copy2(_SOURCE, _COPY)
os.environ["GEMINI_DB_URL"] = f"sqlite:///{_COPY}"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from datetime import date  # noqa: E402
from unittest import mock  # noqa: E402

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import main as app_main  # noqa: E402
from database import engine  # noqa: E402
from services.accounting_service import AccountingService  # noqa: E402
from services.credit_note_service import CreditNoteService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.purchase_service import PurchaseService  # noqa: E402
from services.sales_service import SalesService  # noqa: E402

NEW_COLUMN_DEFAULTS = {
    ("purchase_invoices", "special_discount"): 0,
    ("purchase_invoices", "total_discount"): 0,
    ("purchase_invoice_items", "discount_percent"): 0,
    ("purchase_invoice_items", "discount_amount"): 0,
    ("sales_invoices", "edit_count"): 0,
    ("sales_invoices", "last_edited_date"): None,
    ("stock_transactions", "is_reversed"): 0,
    ("journal_entries", "is_reversed"): 0,
    # Pre-1.1 additive columns (create_db._migrate_add_column, M29c): present on
    # a 1.0.x database already; a db older than that gains them as NULL.
    ("documents", "approval_status"): None,
    ("documents", "approved_by"): None,
    ("documents", "approved_date"): None,
    ("documents", "approval_note"): None,
}


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _snapshot(path) -> dict:
    """{table: (columns, rows)} for every table, straight from SQLite."""
    conn = sqlite3.connect(path)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        result = {}
        for t in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
            rows = conn.execute(f"SELECT {', '.join(cols)} FROM {t} ORDER BY rowid").fetchall()
            result[t] = (cols, rows)
        return result
    finally:
        conn.close()


def _raw_figures(path) -> dict:
    """Totals the way the app computes them, via raw SQL (works pre- and post-patch)."""
    conn = sqlite3.connect(path)
    try:
        q = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
        return {
            "purchase_totals": q("SELECT id, total, taxable_amount FROM purchase_invoices WHERE is_deleted=0 ORDER BY id"),
            "sales_totals": q("SELECT id, total, taxable_amount FROM sales_invoices WHERE is_deleted=0 ORDER BY id"),
            "stock": q("""SELECT i.id, ROUND(i.opening_stock
                              + COALESCE(SUM(CASE WHEN t.type='IN' THEN t.quantity END), 0)
                              - COALESCE(SUM(CASE WHEN t.type='OUT' THEN t.quantity END), 0), 2)
                          FROM items i LEFT JOIN stock_transactions t
                               ON t.item_id = i.id AND t.is_deleted = 0
                          GROUP BY i.id ORDER BY i.id"""),
            "tb": q("""SELECT a.id, ROUND(CASE WHEN a.opening_balance_type='Cr' THEN -a.opening_balance
                                          ELSE a.opening_balance END
                              + COALESCE(SUM(l.debit), 0) - COALESCE(SUM(l.credit), 0), 2)
                       FROM ledger_accounts a
                       LEFT JOIN journal_entry_lines l ON l.account_id = a.id AND l.is_deleted = 0
                            AND l.entry_id IN (SELECT id FROM journal_entries WHERE is_deleted = 0)
                       WHERE a.is_deleted = 0 GROUP BY a.id ORDER BY a.id"""),
        }
    finally:
        conn.close()


def _tb_totals():
    tb = AccountingService.get_trial_balance()
    return round(sum(r["debit"] for r in tb), 2), round(sum(r["credit"] for r in tb), 2)


def main():
    assert os.path.abspath(engine.url.database) == os.path.abspath(_COPY), engine.url
    source_hash = _sha(_SOURCE)
    before = _snapshot(_COPY)
    before_figures = _raw_figures(_COPY)
    print(f"Pre-patch copy of {_SOURCE}: "
          + ", ".join(f"{t}={len(before[t][1])}" for t in
                      ("purchase_invoices", "sales_invoices", "journal_entries", "stock_transactions")))
    assert "schema_migrations" not in before, "source is not a pre-patch database"

    # --- the real startup sequence -----------------------------------------
    app = QApplication.instance() or QApplication([])
    messages = []
    with mock.patch.object(QMessageBox, "information", side_effect=lambda *a: messages.append(a[2])), \
         mock.patch.object(QMessageBox, "critical", side_effect=lambda *a: messages.append("CRITICAL " + a[2])):
        assert app_main._prepare_database(app) is True, messages
    assert len(messages) == 1 and "Applied: 001, 002, 003" in messages[0], messages
    backup = messages[0].rsplit("\n", 1)[-1]
    try:
        _verify(backup, source_hash, before, before_figures)
    finally:
        os.remove(backup)  # a copy of the source db; don't leave it in backups/
    print(f"\nUpgrade path verified on a copy of {os.path.basename(_SOURCE)}. "
          f"The original was not modified: {_sha(_SOURCE) == source_hash}")


def _verify(backup, source_hash, before, before_figures):
    print(f"[1] startup applied 001, 002, 003; backup at {backup}")
    assert _sha(backup) == source_hash, "the backup must be the untouched pre-patch database"
    print("[2] backup is byte-identical to the pre-patch database OK")

    # --- nothing pre-existing changed ----------------------------------------
    after = _snapshot(_COPY)
    for table, (cols, rows) in before.items():
        after_cols, after_rows = after[table]
        idx = [after_cols.index(c) for c in cols]  # every old column must still exist
        projected = [tuple(r[i] for i in idx) for r in after_rows[:len(rows)]]
        assert projected == rows, f"{table}: pre-existing rows changed"
        for col in set(after_cols) - set(cols):
            default = NEW_COLUMN_DEFAULTS.get((table, col), "unexpected")
            assert default != "unexpected", f"unexpected new column {table}.{col}"
            values = {r[after_cols.index(col)] for r in after_rows[:len(rows)]}
            assert values <= {default}, f"{table}.{col} old rows hold {values}, expected {default}"
    print(f"[3] all {sum(len(r) for _c, r in before.values())} pre-existing rows in "
          f"{len(before)} tables unchanged; new columns hold their defaults OK")

    after_figures = _raw_figures(_COPY)
    for key in ("purchase_totals", "sales_totals", "stock"):
        assert after_figures[key] == before_figures[key], key
    tb_after = dict(after_figures["tb"])
    for account_id, balance in before_figures["tb"]:
        assert tb_after.pop(account_id) == balance, f"ledger {account_id} balance changed"
    # Only the new system account (Discount Received) may appear — at zero.
    assert all(balance == 0 for balance in tb_after.values()), tb_after
    for inv_id, total, taxable in before_figures["purchase_totals"]:
        details = PurchaseService().get_purchase_invoice_details(inv_id)
        assert details["total"] == float(total) and details["taxable_amount"] == float(taxable)
        assert details["total_discount"] == 0.0
    for item_id, stock in before_figures["stock"]:
        assert ItemService().get_current_stock(item_id) == stock, item_id
    tb_before = _tb_totals()
    assert tb_before[0] == tb_before[1]
    print(f"[4] every purchase total, sales total and stock figure identical; Trial Balance "
          f"{tb_before[0]:.2f} = {tb_before[1]:.2f}, identical per account to pre-patch OK")

    # --- the three features on the upgraded data ------------------------------
    purchase = PurchaseService().list_purchase_invoices()
    sale = SalesService().list_invoices()
    supplier_id = purchase[0]["supplier_id"] if purchase else None
    item_id = before_figures["stock"][0][0]
    if supplier_id:
        new_bill = PurchaseService().create_purchase_invoice(
            "UPG-DISC-1", date.today(), supplier_id,
            [{"item_id": item_id, "quantity": 10, "rate": 100, "discount_percent": 10}],
            created_by="check_upgrade", special_discount=50,
        )
        assert float(new_bill.taxable_amount) == 850.0
        d, c = _tb_totals()
        assert d == c
        print(f"[5] discounted purchase on upgraded db: taxable 850 (10 x 100 -10% -50); "
              f"TB {d:.2f} = {c:.2f} OK")

        note = CreditNoteService().create_credit_note({
            "credit_note_no": "UPG-CN-1", "credit_note_date": date.today(),
            "supplier_id": supplier_id, "note_type": "COMMERCIAL", "reason": "DISCOUNT",
            "total_amount": 100,
        }, created_by="check_upgrade")
        d, c = _tb_totals()
        assert d == c
        print(f"[6] commercial credit note {note.credit_note_no} on upgraded db; TB {d:.2f} = {c:.2f} OK")

    if sale:
        admin = _an_admin()
        target = sale[-1]  # the oldest pre-patch sale
        details = SalesService().get_invoice_details(target["id"])
        lines = [{"item_id": l["item_id"], "quantity": l["quantity"], "rate": l["rate"]}
                 for l in details["lines"]]
        stock_before = {l["item_id"]: ItemService().get_current_stock(l["item_id"]) for l in lines}
        with mock.patch("services.period_lock_service.PeriodLockService.check_not_locked"):
            # the real db may have a period lock (H6); this check is about the
            # edit mechanics, not the lock, which check_p3 covers.
            SalesService().update_invoice(
                target["id"],
                {"customer_id": details["customer_id"], "date": details["date"], "lines": lines},
                "upgrade-path check: re-post unchanged", admin,
            )
        after_details = SalesService().get_invoice_details(target["id"])
        assert after_details["total"] == details["total"] and after_details["edit_count"] == 1
        for iid, stock in stock_before.items():
            assert ItemService().get_current_stock(iid) == stock
        d, c = _tb_totals()
        assert d == c
        print(f"[7] pre-patch sales invoice {details['invoice_no']} edited (same lines): total "
              f"{after_details['total']:.2f} unchanged, stock unchanged, TB {d:.2f} = {c:.2f} OK")


def _an_admin() -> str:
    conn = sqlite3.connect(_COPY)
    try:
        row = conn.execute("""SELECT u.username FROM users u JOIN roles r ON r.id = u.role_id
                              WHERE r.name = 'Administrator' AND u.is_deleted = 0
                              AND u.is_active = 1 ORDER BY u.id LIMIT 1""").fetchone()
        return row[0]
    finally:
        conn.close()


if __name__ == "__main__":
    main()
