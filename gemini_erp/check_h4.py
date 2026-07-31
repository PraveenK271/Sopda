"""H4 check: purchase import.

Asserts:
- a 2-bill file imports; stock rises by the right amount per item; each bill has
  a balanced journal entry
- supplier outstanding increases by the bill totals
- the SAME bill_no under two different suppliers is accepted (bill_no is unique
  per supplier, not globally)
- re-running the file fails validation on a per-supplier duplicate bill_no

Runs on a DISPOSABLE database (creates real purchase bills). Point GEMINI_DB_URL
at a throwaway SQLite file before running.

Run with: python check_h4.py
"""

import os
import tempfile
from datetime import datetime

from openpyxl import Workbook

from database import DATABASE_URL, get_session
from models import JournalEntry, JournalEntryLine, PurchaseInvoice
from services.accounting_service import AccountingService
from services.import_service import IMPORT_DEFS, ImportService
from services.item_service import ItemService

COLS = IMPORT_DEFS["PURCHASES"].column_names()
AP = "Andhra Pradesh"
KA = "Karnataka"


def _write(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(COLS)
    for r in rows:
        ws.append(r)
    wb.save(path)


def main():
    if "mssql" in DATABASE_URL:
        raise SystemExit("Refusing to run against SQL Server (creates real bills). Use a throwaway SQLite DB.")

    svc = ImportService()
    stamp = datetime.now().strftime("%H%M%S%f")
    tmp = tempfile.mkdtemp(prefix="h4_")

    a = ItemService().add_item(code=f"H4-A-{stamp}", name="Item A", unit="PCS", gst_rate=18, opening_stock=0, created_by="check_h4")
    b = ItemService().add_item(code=f"H4-B-{stamp}", name="Item B", unit="PCS", gst_rate=18, opening_stock=0, created_by="check_h4")
    ca, cb = a.code, b.code

    sa, sb = f"Supp A {stamp}", f"Supp B {stamp}"
    bill = "001"  # SAME bill number under two different suppliers
    # bill_no, bill_date, supplier, gstin, state, item, qty, rate, bill_total
    rows = [
        # Bill 001 / Supp A (AP) -> CGST+SGST. taxable 1300, gst 234 -> 1534
        [bill, "05-04-2026", sa, "37AAAAA0000A1Z5", AP, ca, 10, 80, 1534],
        [bill, "05-04-2026", sa, "37AAAAA0000A1Z5", AP, cb, 5, 100, 1534],
        # Bill 001 / Supp B (KA) -> IGST. taxable 500, igst 90 -> 590
        [bill, "06-04-2026", sb, "29AAAAA0000A1Z5", KA, ca, 5, 100, 590],
    ]
    pf = os.path.join(tmp, "purchases.xlsx")
    _write(pf, rows)

    # Same bill_no / two suppliers must pass validation.
    report = svc.validate(svc.read_sheet(pf, COLS), "PURCHASES")
    assert report.is_importable, f"same bill_no under two suppliers should be accepted: {report.errors}"

    log = svc.import_purchases(pf, "check_h4")
    assert log.status == "IMPORTED" and log.records_created == 2, (log.status, log.records_created)
    assert ItemService().get_current_stock(a.id) == 15, ItemService().get_current_stock(a.id)  # 10 + 5
    assert ItemService().get_current_stock(b.id) == 5, ItemService().get_current_stock(b.id)
    print("Imported 2 bills (same bill_no, two suppliers); stock A 0->15, B 0->5")

    outs = {r["name"]: r["outstanding"] for r in AccountingService.get_outstanding_suppliers()}
    assert abs(outs.get(sa, 0) - 1534) < 0.01, outs
    assert abs(outs.get(sb, 0) - 590) < 0.01, outs
    print(f"Supplier outstanding: {sa}=1534, {sb}=590")

    # Balanced journal per bill.
    s = get_session()
    try:
        bills = s.query(PurchaseInvoice).filter(PurchaseInvoice.invoice_no == bill).all()
        assert len(bills) == 2, f"expected 2 bills numbered 001, got {len(bills)}"
        for bi in bills:
            entry = s.query(JournalEntry).filter(
                JournalEntry.reference_type == "PURCHASE", JournalEntry.reference_id == bi.id
            ).one()
            lines = s.query(JournalEntryLine).filter(JournalEntryLine.entry_id == entry.id).all()
            dr = sum(float(l.debit) for l in lines)
            cr = sum(float(l.credit) for l in lines)
            assert abs(dr - cr) < 0.01, f"bill {bi.id} journal unbalanced {dr} vs {cr}"
    finally:
        s.close()
    print("Two separate bills numbered 001; each journal balanced")

    # Re-run -> per-supplier duplicate.
    report2 = svc.validate(svc.read_sheet(pf, COLS), "PURCHASES")
    assert not report2.is_importable
    assert any("already exists for supplier" in e["message"] for e in report2.errors), report2.errors
    try:
        svc.import_purchases(pf, "check_h4")
        raise AssertionError("re-run was not refused")
    except ValueError:
        pass
    print("Re-running fails on per-supplier duplicate bill_no")

    print("PASS")


if __name__ == "__main__":
    main()
