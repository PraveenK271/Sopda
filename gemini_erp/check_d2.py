"""Patch v1.2.0 D2 check: correct a wrong invoice number (a label change only).

Asserts:
- stock is COMPLETELY unchanged: same stock-transaction rows (count and
  content) and the same current stock, before and after
- the journal entries' amounts and dates are unchanged; only the narration
  differs, and only where it named the old number (INV1 never touches INV10)
- the corrected number appears in the Sales Log, the PDF and the customer ledger
- raises: a number that already exists; one held by a CANCELLED invoice (also
  differing only in case); a cancelled invoice; an invoice dated on or before
  the GST filed-up-to date; a non-Administrator; an empty reason; a number
  failing the same format rule as a new invoice (>16 chars, spaces)
- sales_invoice_audit holds a NUMBER_CORRECTION row with both snapshots

ALWAYS runs on a throwaway SQLite file (GEMINI_DB_URL overridden below).

Run with: python check_d2.py
"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="gemini_check_d2_")
os.environ["GEMINI_DB_URL"] = f"sqlite:///{os.path.join(_TMP, 'check_d2.db')}"

import base64  # noqa: E402
import re  # noqa: E402
import zlib  # noqa: E402
from datetime import date, timedelta  # noqa: E402

from sqlalchemy import text  # noqa: E402

from create_db import initialize_database  # noqa: E402
from database import engine, get_session  # noqa: E402
from models import JournalEntry, Role, SalesInvoice  # noqa: E402
from reports.invoice_pdf import generate_invoice_pdf  # noqa: E402
from services.accounting_service import AccountingService  # noqa: E402
from services.auth_service import AuthService  # noqa: E402
from services.customer_service import CustomerService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.migration_service import MigrationService  # noqa: E402
from services.permissions import ROLE_ACCOUNTANT, ROLE_ADMINISTRATOR  # noqa: E402
from services.sales_service import ACTION_NUMBER_CORRECTION, SalesService  # noqa: E402
from services.settings_service import SettingsService  # noqa: E402

TODAY = date.today()
PREV_MONTH_DAY = (TODAY.replace(day=1) - timedelta(days=1)).replace(day=15)
ADMIN, ACCOUNTANT = "d2_admin", "d2_accountant"
sales = SalesService()


def _setup():
    assert "check_d2" in str(engine.url), f"refusing to run on {engine.url}"
    initialize_database()
    session = get_session()
    try:
        MigrationService().run_pending(session, applied_by="check_d2")
        auth = AuthService()
        for username, role_name in ((ADMIN, ROLE_ADMINISTRATOR), (ACCOUNTANT, ROLE_ACCOUNTANT)):
            role = session.query(Role).filter(Role.name == role_name).one()
            auth.create_user(session, username, "Check@12345", username, role.id)
    finally:
        session.close()


def _raises(fn, exc_type, fragment):
    try:
        fn()
    except exc_type as exc:
        assert fragment.lower() in str(exc).lower(), (fragment, str(exc))
        return
    raise AssertionError(f"expected {exc_type.__name__} containing '{fragment}'")


def _pdf_text(path) -> str:
    """Decoded content streams of a ReportLab PDF (ASCII85 + Flate)."""
    raw = open(path, "rb").read()
    out = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        chunk = match.group(1).strip()
        try:
            out.append(zlib.decompress(base64.a85decode(chunk.removesuffix(b"~>"))).decode("latin-1"))
        except Exception:
            continue
    return "\n".join(out)


def _stock_rows():
    with engine.connect() as conn:
        return conn.execute(text("SELECT * FROM stock_transactions ORDER BY id")).fetchall()


def _journals(invoice_id):
    session = get_session()
    try:
        entries = (
            session.query(JournalEntry)
            .filter(JournalEntry.reference_id == invoice_id, JournalEntry.reference_type.like("SALE%"))
            .order_by(JournalEntry.id)
            .all()
        )
        return [
            (e.id, e.date, e.reference_type, e.narration,
             tuple((l.account_id, float(l.debit), float(l.credit)) for l in e.lines))
            for e in entries
        ]
    finally:
        session.close()


def main():
    _setup()
    item = ItemService().add_item(code="D2-I", name="D2 Item", gst_rate=18, opening_stock=100).id
    cust = CustomerService().add_customer(name="D2 Buyer", state="Andhra Pradesh").id
    line = [{"item_id": item, "quantity": 10, "rate": 100}]

    typo = sales.create_invoice("INV1", TODAY, cust, line, created_by=ADMIN).id
    neighbour = sales.create_invoice("INV10", TODAY, cust, line, created_by=ADMIN).id
    sales.update_invoice(typo, {"customer_id": cust, "lines": [{**line[0], "quantity": 9}]}, "qty", ADMIN)

    stock_before, stock_rows_before = ItemService().get_current_stock(item), _stock_rows()
    journals_before, neighbour_before = _journals(typo), _journals(neighbour)

    corrected = sales.correct_invoice_number(typo, " INV-0001 ", "typed INV1 instead of INV-0001", ADMIN)
    assert corrected.invoice_no == "INV-0001"

    # [1] stock completely unchanged
    assert _stock_rows() == stock_rows_before and ItemService().get_current_stock(item) == stock_before
    print(f"[1] stock untouched: {len(stock_rows_before)} stock rows identical, current stock "
          f"{stock_before:g} OK")

    # [2] journals: amounts/dates/lines identical; narration only, bounded
    journals_after = _journals(typo)
    assert len(journals_after) == len(journals_before) == 3  # sale, edit reversal, re-post
    for before, after in zip(journals_before, journals_after):
        assert (before[0], before[1], before[2], before[4]) == (after[0], after[1], after[2], after[4])
        assert "INV1 " not in after[3] + " " and "INV-0001" in after[3], after[3]
        assert after[3] == re.sub(r"Sales Invoice INV1(?![A-Za-z0-9/-])", "Sales Invoice INV-0001", before[3])
    assert _journals(neighbour) == neighbour_before, "INV10's narration must not be touched"
    print("[2] 3 journals: ids, dates, types, accounts and amounts identical; narrations now "
          "name INV-0001; INV10 untouched OK")

    # [3] visible everywhere
    listed = {inv["id"]: inv["invoice_no"] for inv in sales.list_invoices()}
    assert listed[typo] == "INV-0001"
    pdf_text = _pdf_text(generate_invoice_pdf(typo, os.path.join(_TMP, "corrected.pdf")))
    assert "INV-0001" in pdf_text and "(INV1)" not in pdf_text
    session = get_session()
    try:
        ledger_id = session.get(SalesInvoice, typo).customer.ledger_account.id
    finally:
        session.close()
    narrations = [e["narration"] for e in AccountingService.get_ledger(ledger_id)["entries"]]
    assert any("Sales Invoice INV-0001" in n for n in narrations)
    assert not any(re.search(r"Sales Invoice INV1(?![0-9])", n) for n in narrations), narrations
    print("[3] corrected number in the Sales Log, the PDF text and the customer ledger OK")

    # [4] audit
    history = sales.get_edit_history(typo)
    assert [h["action"] for h in history] == ["EDIT", ACTION_NUMBER_CORRECTION]
    assert history[1]["before"]["invoice_no"] == "INV1" and history[1]["after"]["invoice_no"] == "INV-0001"
    assert sales.get_invoice_details(typo)["edit_count"] == 1, "a correction is not an edit"
    print("[4] audit row NUMBER_CORRECTION, snapshots INV1 -> INV-0001; edit_count unchanged OK")

    # [5] guards
    other = sales.create_invoice("INV-0002", TODAY, cust, line, created_by=ADMIN).id
    void = sales.create_invoice("INV-0003", TODAY, cust, line, created_by=ADMIN).id
    sales.cancel_invoice(void, "void", ADMIN)
    _raises(lambda: sales.correct_invoice_number(other, "INV10", "x", ADMIN), ValueError, "already used")
    _raises(lambda: sales.correct_invoice_number(other, "INV-0003", "x", ADMIN), ValueError, "cancelled")
    _raises(lambda: sales.correct_invoice_number(other, "inv-0003", "x", ADMIN), ValueError, "cancelled")
    _raises(lambda: sales.correct_invoice_number(void, "INV-0099", "x", ADMIN), ValueError, "cancelled")
    _raises(lambda: sales.correct_invoice_number(other, "INV-0099", "x", ACCOUNTANT), PermissionError, "Administrator")
    _raises(lambda: sales.correct_invoice_number(other, "INV-0099", " ", ADMIN), ValueError, "reason")
    _raises(lambda: sales.correct_invoice_number(other, "INV-0002", "x", ADMIN), ValueError, "same")
    _raises(lambda: sales.correct_invoice_number(other, "INV 0099", "x", ADMIN), ValueError, "only letters")
    _raises(lambda: sales.correct_invoice_number(other, "INV-2026-27-00099", "x", ADMIN), ValueError, "16")
    _raises(lambda: sales.create_invoice("INV 0099", TODAY, cust, line, created_by=ADMIN), ValueError, "only letters")

    filed = sales.create_invoice("INV-0004", PREV_MONTH_DAY, cust, line, created_by=ADMIN).id
    assert any("never been set" in w for w in sales.preview_number_correction(filed, "INV-0005", "x", ADMIN))
    SettingsService().set_gst_filed_upto_date(PREV_MONTH_DAY, ADMIN)
    _raises(lambda: sales.correct_invoice_number(filed, "INV-0005", "x", ADMIN), ValueError, "GSTR-1")
    assert sales.get_invoice_details(other)["invoice_no"] == "INV-0002"
    print("[5] raise: existing number, number held by a cancelled invoice (any case), "
          "cancelled invoice, Accountant, empty reason, same number, bad format (space / "
          ">16 chars, also on a new invoice), filed GST period OK")
    print("\nAll D2 (invoice number correction) checks passed.")


if __name__ == "__main__":
    main()
