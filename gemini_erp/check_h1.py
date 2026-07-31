"""H1 check: the import engine + template generator.

Asserts:
- generate_template('SALES') produces a file whose headers read_sheet() accepts
  (the example row is skipped)
- a misspelled header is rejected, naming the missing column
- a file with a bad date, a zero quantity and an unknown item code produces
  EXACTLY 3 errors, at the correct row numbers
- validation writes NOTHING: sales_invoices / stock_transactions /
  journal_entries row counts are unchanged

Run with: python check_h1.py
"""

import os
import tempfile
from datetime import datetime

from openpyxl import Workbook

from database import get_session
from models import JournalEntry, SalesInvoice, StockTransaction
from services.import_service import IMPORT_DEFS, ImportService
from services.item_service import ItemService

SALES_COLS = IMPORT_DEFS["SALES"].column_names()


def _counts():
    session = get_session()
    try:
        return (
            session.query(SalesInvoice).count(),
            session.query(StockTransaction).count(),
            session.query(JournalEntry).count(),
        )
    finally:
        session.close()


def _write_sales(path, header, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)


def main():
    svc = ImportService()
    stamp = datetime.now().strftime("%H%M%S%f")
    tmp = tempfile.mkdtemp(prefix="h1_")

    # A real item so the "valid" rows reference something that exists.
    item_code = f"H1-ITEM-{stamp}"
    ItemService().add_item(code=item_code, name="H1 Test Item", unit="PCS", gst_rate=18,
                           opening_stock=0, created_by="check_h1")

    # 1. Template round-trips: read_sheet accepts the generated headers.
    tpl = os.path.join(tmp, "sales_template.xlsx")
    svc.generate_template("SALES", tpl)
    rows = svc.read_sheet(tpl, SALES_COLS)
    assert rows == [], f"template should have no data rows after skipping the example, got {rows}"
    print("Template generated; read_sheet accepts its headers (example row skipped)")

    # 2. Misspelled header is rejected, naming the column.
    bad_header = os.path.join(tmp, "bad_header.xlsx")
    header = list(SALES_COLS)
    header[0] = "invoice_number"  # should be invoice_no
    _write_sales(bad_header, header, [])
    try:
        svc.read_sheet(bad_header, SALES_COLS)
        raise AssertionError("misspelled header was not rejected")
    except ValueError as exc:
        assert "invoice_no" in str(exc), f"error should name the column: {exc}"
    print("Misspelled header rejected, naming 'invoice_no'")

    # 3. Bad date + zero qty + unknown item -> exactly 3 errors at rows 3,4,5.
    errfile = os.path.join(tmp, "errors.xlsx")
    _write_sales(errfile, SALES_COLS, [
        # row 2: valid
        [f"INV-{stamp}-A", "05-04-2026", "Cust One", "", "", item_code, 2, 100, 236],
        # row 3: bad date format
        [f"INV-{stamp}-B", "2026/04/05", "Cust One", "", "", item_code, 1, 100, 118],
        # row 4: zero quantity
        [f"INV-{stamp}-C", "06-04-2026", "Cust One", "", "", item_code, 0, 100, 0],
        # row 5: unknown item code
        [f"INV-{stamp}-D", "07-04-2026", "Cust One", "", "", f"NOPE-{stamp}", 1, 100, 118],
    ])

    before = _counts()
    rows = svc.read_sheet(errfile, SALES_COLS)
    report = svc.validate(rows, "SALES")
    after = _counts()

    assert len(report.errors) == 3, f"expected 3 errors, got {len(report.errors)}: {report.errors}"
    error_rows = sorted(e["row_number"] for e in report.errors)
    assert error_rows == [3, 4, 5], f"expected errors on rows 3,4,5, got {error_rows}"
    assert not report.is_importable
    print(f"Exactly 3 errors at rows {error_rows}: "
          + " | ".join(f"r{e['row_number']}: {e['message']}" for e in report.errors))

    # 4. Nothing written.
    assert before == after, f"validation wrote to the DB! before={before} after={after}"
    print(f"Nothing written — counts unchanged {before}")

    print("PASS")


if __name__ == "__main__":
    main()
