"""H3 check: sales import.

Asserts:
- a 3-invoice / 7-line file imports; stock drops by the right amount per item;
  every invoice has a balanced journal entry
- an AP customer produces CGST+SGST; an out-of-state customer produces IGST
- a file with a deliberately wrong invoice_total on one invoice fails validation
  naming that invoice, and writes NOTHING
- re-running the same file fails validation on duplicate invoice_no

Runs on a DISPOSABLE database (creates real backdated invoices). Point
GEMINI_DB_URL at a throwaway SQLite file before running.

Run with: python check_h3.py
"""

import os
import tempfile
from datetime import datetime

from openpyxl import Workbook

from database import DATABASE_URL, get_session
from models import JournalEntry, JournalEntryLine, SalesInvoice
from services.accounting_service import AccountingService
from services.import_service import IMPORT_DEFS, ImportService
from services.item_service import ItemService

COLS = IMPORT_DEFS["SALES"].column_names()
AP = "Andhra Pradesh"
KA = "Karnataka"


def _write(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(COLS)
    for r in rows:
        ws.append(r)
    wb.save(path)


def _count_invoices():
    s = get_session()
    try:
        return s.query(SalesInvoice).count()
    finally:
        s.close()


def main():
    if "mssql" in DATABASE_URL:
        raise SystemExit("Refusing to run against SQL Server (creates real invoices). Use a throwaway SQLite DB.")

    svc = ImportService()
    stamp = datetime.now().strftime("%H%M%S%f")
    tmp = tempfile.mkdtemp(prefix="h3_")

    a = ItemService().add_item(code=f"H3-A-{stamp}", name="Item A", unit="PCS", gst_rate=18, opening_stock=100, created_by="check_h3")
    b = ItemService().add_item(code=f"H3-B-{stamp}", name="Item B", unit="PCS", gst_rate=18, opening_stock=100, created_by="check_h3")
    ca, cb = a.code, b.code

    inv1, inv2, inv3 = f"H3-INV1-{stamp}", f"H3-INV2-{stamp}", f"H3-INV3-{stamp}"
    # invoice_no, date, customer, gstin, state, item, qty, rate, invoice_total
    valid_rows = [
        # INV1 — AP customer, CGST+SGST. taxable 2000, gst 360 -> 2360
        [inv1, "05-04-2026", "AP Cust", "37AAAAA0000A1Z5", AP, ca, 10, 100, 2360],
        [inv1, "05-04-2026", "AP Cust", "37AAAAA0000A1Z5", AP, cb, 5, 200, 2360],
        # INV2 — Karnataka customer, IGST. taxable 900, igst 162 -> 1062
        [inv2, "06-04-2026", "KA Cust", "29AAAAA0000A1Z5", KA, ca, 4, 100, 1062],
        [inv2, "06-04-2026", "KA Cust", "29AAAAA0000A1Z5", KA, cb, 2, 200, 1062],
        [inv2, "06-04-2026", "KA Cust", "29AAAAA0000A1Z5", KA, ca, 1, 100, 1062],
        # INV3 — AP customer. taxable 500, gst 108 -> 590
        [inv3, "07-04-2026", "AP Cust", "37AAAAA0000A1Z5", AP, ca, 3, 100, 590],
        [inv3, "07-04-2026", "AP Cust", "37AAAAA0000A1Z5", AP, cb, 1, 200, 590],
    ]
    valid_file = os.path.join(tmp, "sales.xlsx")
    _write(valid_file, valid_rows)

    # --- wrong total on INV1 fails validation, writes nothing ---
    wrong_rows = [list(r) for r in valid_rows]
    wrong_rows[0][8] = 9999  # INV1 sheet total wrong
    wrong_rows[1][8] = 9999
    wrong_file = os.path.join(tmp, "wrong.xlsx")
    _write(wrong_file, wrong_rows)

    before = _count_invoices()
    report = svc.validate(svc.read_sheet(wrong_file, COLS), "SALES")
    assert not report.is_importable, "wrong total should fail validation"
    assert any(inv1 in e["message"] and "mismatch" in e["message"] for e in report.errors), report.errors
    try:
        svc.import_sales(wrong_file, "check_h3")
        raise AssertionError("import of wrong-total file was not refused")
    except ValueError:
        pass
    assert _count_invoices() == before, "a rejected file wrote invoices!"
    print("Wrong invoice_total: validation names the invoice; nothing written")

    # --- valid import ---
    log = svc.import_sales(valid_file, "check_h3")
    assert log.status == "IMPORTED" and log.records_created == 3, (log.status, log.records_created)
    assert ItemService().get_current_stock(a.id) == 82, ItemService().get_current_stock(a.id)  # 100 - (10+4+1+3)
    assert ItemService().get_current_stock(b.id) == 92, ItemService().get_current_stock(b.id)  # 100 - (5+2+1)
    print("Imported 3 invoices; stock A 100->82, B 100->92")

    s = get_session()
    try:
        i1 = s.query(SalesInvoice).filter(SalesInvoice.invoice_no == inv1).one()
        i2 = s.query(SalesInvoice).filter(SalesInvoice.invoice_no == inv2).one()
        i3 = s.query(SalesInvoice).filter(SalesInvoice.invoice_no == inv3).one()
        assert float(i1.cgst) > 0 and float(i1.sgst) > 0 and float(i1.igst) == 0, "INV1 should be CGST+SGST"
        assert float(i2.igst) > 0 and float(i2.cgst) == 0 and float(i2.sgst) == 0, "INV2 should be IGST"
        assert float(i1.total) == 2360 and float(i2.total) == 1062
        # each invoice has a balanced journal entry
        for inv in (i1, i2, i3):
            entry = s.query(JournalEntry).filter(
                JournalEntry.reference_type == "SALE", JournalEntry.reference_id == inv.id
            ).one()
            lines = s.query(JournalEntryLine).filter(JournalEntryLine.entry_id == entry.id).all()
            dr = sum(float(l.debit) for l in lines)
            cr = sum(float(l.credit) for l in lines)
            assert abs(dr - cr) < 0.01, f"invoice {inv.invoice_no} journal unbalanced {dr} vs {cr}"
    finally:
        s.close()
    print("AP invoice CGST+SGST, KA invoice IGST; all journals balanced")

    # --- negative stock is allowed and recorded in the ImportLog notes ---
    neg = ItemService().add_item(code=f"H3-NEG-{stamp}", name="Scarce Item", unit="PCS",
                                 gst_rate=18, opening_stock=2, created_by="check_h3")
    neg_inv = f"H3-NEG-INV-{stamp}"
    neg_file = os.path.join(tmp, "neg.xlsx")
    _write(neg_file, [[neg_inv, "08-04-2026", "AP Cust", "37AAAAA0000A1Z5", AP, neg.code, 5, 100, 590]])
    neg_log = svc.import_sales(neg_file, "check_h3")
    assert neg_log.status == "IMPORTED" and neg_log.records_created == 1
    assert ItemService().get_current_stock(neg.id) == -3, ItemService().get_current_stock(neg.id)
    assert neg_log.notes and "below zero" in neg_log.notes, f"negative not recorded in notes: {neg_log.notes}"
    print("Negative stock allowed (2 - 5 = -3) and recorded in ImportLog notes")

    # --- re-run fails on duplicate invoice_no ---
    report2 = svc.validate(svc.read_sheet(valid_file, COLS), "SALES")
    assert not report2.is_importable
    assert any("already exists" in e["message"] for e in report2.errors), report2.errors
    try:
        svc.import_sales(valid_file, "check_h3")
        raise AssertionError("re-run was not refused")
    except ValueError:
        pass
    print("Re-running the same file fails on duplicate invoice_no")

    print("PASS")


if __name__ == "__main__":
    main()
