"""Release check: the UPGRADE PATH on a real earlier-version database.

Takes a COPY of an earlier database (default: gemini_erp.db next to this file,
a v1.0.x database; or the path given as the first argument — for v1.2.0 that
must be a restored copy of v1.1.0 LIVE data), points the app at the copy, runs
the real startup sequence (main._prepare_database), and proves:
- exactly the migrations the source lacked were applied, and the automatic
  backup is byte-identical to the source
- every pre-existing row of every pre-existing table is unchanged in every
  pre-existing column (nothing destroyed, altered or orphaned); new columns
  hold their neutral defaults — every pre-patch invoice is status 'ACTIVE'
- every purchase total, sales total, stock figure and ledger balance is
  identical before and after (Rule B), and every pre-patch invoice appears in
  the Sales Log, the Sales Register / HSN / GSTR-3B totals exactly as before
- the new features then work on that same database, books balanced after each:
  v1.1.0 (discounted purchase, credit note, invoice edit) and v1.2.0 (number
  correction; cancelling an invoice — one EDITED under v1.1.0 when present)

The original database file is never opened for writing.

Run with: python check_upgrade_path.py [path\\to\\earlier_version.db]
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
from services.gst_report_service import GstReportService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.migration_service import MigrationService  # noqa: E402
from services.purchase_service import PurchaseService  # noqa: E402
from services.sales_service import SalesService  # noqa: E402

NEW_COLUMN_DEFAULTS = {
    # v1.1.0
    ("purchase_invoices", "special_discount"): 0,
    ("purchase_invoices", "total_discount"): 0,
    ("purchase_invoice_items", "discount_percent"): 0,
    ("purchase_invoice_items", "discount_amount"): 0,
    ("sales_invoices", "edit_count"): 0,
    ("sales_invoices", "last_edited_date"): None,
    ("stock_transactions", "is_reversed"): 0,
    ("journal_entries", "is_reversed"): 0,
    # v1.2.0
    ("sales_invoices", "status"): "ACTIVE",
    ("sales_invoices", "cancelled_date"): None,
    ("sales_invoices", "cancelled_by"): None,
    ("sales_invoices", "cancellation_reason"): None,
    ("sales_invoice_audit", "action"): "EDIT",
    ("company_profile", "gst_filed_upto_date"): None,
    # Pre-1.1 additive columns (create_db._migrate_add_column, M29c): present on
    # a 1.0.x database already; a db older than that gains them as NULL.
    ("documents", "approval_status"): None,
    ("documents", "approved_by"): None,
    ("documents", "approved_date"): None,
    ("documents", "approval_note"): None,
}
FAR_PAST, FAR_FUTURE = date(2000, 1, 1), date(2100, 12, 31)


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
            "sales_lines": q("""SELECT ROUND(COALESCE(SUM(l.amount), 0), 2), ROUND(COALESCE(SUM(l.quantity), 0), 2)
                                FROM sales_invoice_items l JOIN sales_invoices s ON s.id = l.invoice_id
                                WHERE l.is_deleted = 0 AND s.is_deleted = 0"""),
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


def _applied_in_source(snapshot) -> set[str]:
    if "schema_migrations" not in snapshot:
        return set()
    cols, rows = snapshot["schema_migrations"]
    return {r[cols.index("version")] for r in rows}


def _tb_totals():
    tb = AccountingService.get_trial_balance()
    return round(sum(r["debit"] for r in tb), 2), round(sum(r["credit"] for r in tb), 2)


def _balanced(label):
    d, c = _tb_totals()
    assert d == c, (label, d, c)
    return f"TB {d:.2f} = {c:.2f}"


def main():
    assert os.path.abspath(engine.url.database) == os.path.abspath(_COPY), engine.url
    source_hash = _sha(_SOURCE)
    before = _snapshot(_COPY)
    before_figures = _raw_figures(_COPY)
    already = _applied_in_source(before)
    expected = sorted(m.VERSION for m in MigrationService.discover_migrations() if m.VERSION not in already)
    print(f"Source {_SOURCE}: migrations already applied {sorted(already) or 'none'}; "
          + ", ".join(f"{t}={len(before[t][1])}" for t in
                      ("purchase_invoices", "sales_invoices", "journal_entries", "stock_transactions")))
    assert expected, "source is already at this version — nothing to upgrade"

    # --- the real startup sequence -----------------------------------------
    app = QApplication.instance() or QApplication([])
    messages = []
    with mock.patch.object(QMessageBox, "information", side_effect=lambda *a: messages.append(a[2])), \
         mock.patch.object(QMessageBox, "critical", side_effect=lambda *a: messages.append("CRITICAL " + a[2])):
        assert app_main._prepare_database(app) is True, messages
    assert len(messages) == 1 and f"Applied: {', '.join(expected)}" in messages[0], messages
    backup = messages[0].rsplit("\n", 1)[-1]
    try:
        _verify(backup, source_hash, before, before_figures, expected)
    finally:
        os.remove(backup)  # a copy of the source db; don't leave it in backups/
    print(f"\nUpgrade path verified on a copy of {os.path.basename(_SOURCE)}. "
          f"The original was not modified: {_sha(_SOURCE) == source_hash}")


def _verify(backup, source_hash, before, before_figures, expected):
    print(f"[1] startup applied {', '.join(expected)}; backup at {backup}")
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
    for key in ("purchase_totals", "sales_totals", "sales_lines", "stock"):
        assert after_figures[key] == before_figures[key], key
    tb_after = dict(after_figures["tb"])
    for account_id, balance in before_figures["tb"]:
        assert tb_after.pop(account_id) == balance, f"ledger {account_id} balance changed"
    # Only newly seeded system accounts may appear — at zero.
    assert all(balance == 0 for balance in tb_after.values()), tb_after
    for inv_id, total, taxable in before_figures["purchase_totals"]:
        details = PurchaseService().get_purchase_invoice_details(inv_id)
        assert details["total"] == float(total) and details["taxable_amount"] == float(taxable)
    for item_id, stock in before_figures["stock"]:
        assert ItemService().get_current_stock(item_id) == stock, item_id
    print(f"[4] every purchase total, sales total and stock figure identical; "
          f"{_balanced('after upgrade')}, identical per account to pre-patch OK")

    # --- every pre-patch invoice is ACTIVE and in every report ----------------
    sales = SalesService()
    listed = sales.list_invoices()
    sales_ids = {row[0] for row in before_figures["sales_totals"]}
    assert {inv["id"] for inv in listed} == sales_ids
    assert all(inv["status"] == "ACTIVE" for inv in listed)
    assert {inv["id"] for inv in sales.list_invoices(include_cancelled=False)} == sales_ids
    register = GstReportService.get_sales_register(FAR_PAST, FAR_FUTURE)
    line_taxable, line_qty = before_figures["sales_lines"][0]
    assert round(sum(r["taxable_amount"] for r in register), 2) == line_taxable
    hsn = GstReportService.get_hsn_summary(FAR_PAST, FAR_FUTURE, "SALES")
    assert round(sum(r["quantity"] for r in hsn), 2) == line_qty
    header_taxable = round(sum(row[2] for row in before_figures["sales_totals"]), 2)
    assert GstReportService.get_gstr3b_summary(FAR_PAST, FAR_FUTURE)["outward_taxable_supplies"][
        "taxable_amount"] == header_taxable
    assert GstReportService.get_cancelled_sales_register(FAR_PAST, FAR_FUTURE) == []
    print(f"[5] all {len(listed)} pre-patch invoices ACTIVE; Sales Log, Sales Register "
          f"(taxable {line_taxable:,.2f}), HSN (qty {line_qty:g}) and GSTR-3B outward "
          f"({header_taxable:,.2f}) include every one; nothing listed as cancelled OK")

    # --- the features on the upgraded data -------------------------------------
    admin = _an_admin()
    purchase = PurchaseService().list_purchase_invoices()
    supplier_id = purchase[0]["supplier_id"] if purchase else None
    item_id = before_figures["stock"][0][0]
    if supplier_id:
        new_bill = PurchaseService().create_purchase_invoice(
            "UPG-DISC-1", date.today(), supplier_id,
            [{"item_id": item_id, "quantity": 10, "rate": 100, "discount_percent": 10}],
            created_by="check_upgrade", special_discount=50,
        )
        assert float(new_bill.taxable_amount) == 850.0
        CreditNoteService().create_credit_note({
            "credit_note_no": "UPG-CN-1", "credit_note_date": date.today(),
            "supplier_id": supplier_id, "note_type": "COMMERCIAL", "reason": "DISCOUNT",
            "total_amount": 100,
        }, created_by="check_upgrade")
        print(f"[6] v1.1.0 features: discounted purchase (taxable 850) + credit note; "
              f"{_balanced('v1.1 features')} OK")

    if not listed:
        return
    # The real db may carry a period lock (H6) and, after this check sets
    # nothing, an unset GST date; these checks are about the mechanics on old
    # data — the guards themselves are covered by check_p3 / check_d1 / check_d2.
    with mock.patch("services.period_lock_service.PeriodLockService.check_not_locked"):
        # v1.1.0 edit on a pre-patch invoice (no change of lines)
        target = listed[-1]
        details = sales.get_invoice_details(target["id"])
        lines = [{"item_id": l["item_id"], "quantity": l["quantity"], "rate": l["rate"]}
                 for l in details["lines"]]
        sales.update_invoice(
            target["id"], {"customer_id": details["customer_id"], "date": details["date"], "lines": lines},
            "upgrade-path check: re-post unchanged", admin,
        )
        assert sales.get_invoice_details(target["id"])["total"] == details["total"]
        print(f"[7] v1.1.0 edit of {details['invoice_no']} (same lines): total unchanged; "
              f"{_balanced('edit')} OK")

        # v1.2.0: correct a number — stock rows untouched
        stock_rows_before = _snapshot(_COPY)["stock_transactions"]
        corrected = sales.correct_invoice_number(target["id"], "UPG-RENUM-1", "upgrade check", admin)
        assert corrected.invoice_no == "UPG-RENUM-1"
        assert _snapshot(_COPY)["stock_transactions"] == stock_rows_before
        print(f"[8] v1.2.0 number correction {details['invoice_no']} -> UPG-RENUM-1: stock rows "
              f"identical; {_balanced('renumber')} OK")

        # v1.2.0: cancel — prefer an invoice EDITED before this upgrade, the
        # case that proves is_reversed carries across the two patches
        edited_before = [inv for inv in listed if inv["edit_count"] and inv["id"] != target["id"]]
        victim = (edited_before or [inv for inv in listed if inv["id"] != target["id"]] or [target])[0]
        victim_details = sales.get_invoice_details(victim["id"])
        expected_stock = {
            l["item_id"]: ItemService().get_current_stock(l["item_id"]) for l in victim_details["lines"]
        }
        for l in victim_details["lines"]:
            expected_stock[l["item_id"]] += l["quantity"]
        sales.cancel_invoice(victim["id"], "upgrade-path check", admin)
        for iid, stock in expected_stock.items():
            assert ItemService().get_current_stock(iid) == stock, (iid, stock)
        kind = (f"edited {victim['edit_count']}x under v1.1.0" if victim["edit_count"]
                else "pre-patch")
        print(f"[9] v1.2.0 cancel of {victim_details['invoice_no']} ({kind}): only the lines in "
              f"force returned to stock; {_balanced('cancel')}; it leaves every sales total OK")
        assert victim["id"] not in {inv["id"] for inv in sales.list_invoices(include_cancelled=False)}


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
