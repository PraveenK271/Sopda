"""H5 check: receipts & payments import.

Asserts:
- receipts covering an invoice in full drop that customer's outstanding to zero
  and raise the Cash/Bank ledger by the amount received
- an unknown bank_account_name is an ERROR; an unknown party is an ERROR
- a receipt beyond what's owed is allowed but WARNS (balance would go credit)
- payments work the mirror way (supplier outstanding drops to zero)

Runs on a DISPOSABLE database. Point GEMINI_DB_URL at a throwaway SQLite file.

Run with: python check_h5.py
"""

import os
import tempfile
from datetime import datetime

from openpyxl import Workbook

from database import DATABASE_URL, get_session
from models import BankAccount, Customer, JournalEntryLine, LedgerAccount
from services.accounting_service import AccountingService
from services.banking_service import BankingService
from services.import_service import IMPORT_DEFS, ImportService
from services.item_service import ItemService

AP = "Andhra Pradesh"


def _write(path, import_type, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(IMPORT_DEFS[import_type].column_names())
    for r in rows:
        ws.append(r)
    wb.save(path)


def _bank_ledger_balance(bank_id):
    s = get_session()
    try:
        ledger = s.query(LedgerAccount).filter(LedgerAccount.bank_account_id == bank_id).one()
        lines = s.query(JournalEntryLine).filter(JournalEntryLine.account_id == ledger.id).all()
        return sum(float(l.debit) - float(l.credit) for l in lines)
    finally:
        s.close()


def _outstanding(name, suppliers=False):
    rows = (AccountingService.get_outstanding_suppliers() if suppliers
            else AccountingService.get_outstanding_customers())
    return next((r["outstanding"] for r in rows if r["name"] == name), 0.0)


def main():
    if "mssql" in DATABASE_URL:
        raise SystemExit("Refusing to run against SQL Server. Use a throwaway SQLite DB.")

    svc = ImportService()
    stamp = datetime.now().strftime("%H%M%S%f")
    tmp = tempfile.mkdtemp(prefix="h5_")
    item = ItemService().add_item(code=f"H5-A-{stamp}", name="Item", unit="PCS", gst_rate=18, opening_stock=100, created_by="check_h5")

    cust = f"H5 Cust {stamp}"
    supp = f"H5 Supp {stamp}"
    # A sale -> customer auto-created, outstanding 1180.
    sf = os.path.join(tmp, "sales.xlsx")
    _write(sf, "SALES", [[f"H5-INV-{stamp}", "05-04-2026", cust, "37AAAAA0000A1Z5", AP, item.code, 10, 100, 1180]])
    svc.import_sales(sf, "check_h5")
    assert abs(_outstanding(cust) - 1180) < 0.01, _outstanding(cust)

    # A purchase -> supplier auto-created, payable 590.
    pf = os.path.join(tmp, "purch.xlsx")
    _write(pf, "PURCHASES", [[f"H5-BILL-{stamp}", "05-04-2026", supp, "37AAAAA0000A1Z5", AP, item.code, 5, 100, 590]])
    svc.import_purchases(pf, "check_h5")
    assert abs(_outstanding(supp, suppliers=True) - 590) < 0.01, _outstanding(supp, suppliers=True)

    bank = BankingService().add_bank_account(name=f"H5 Bank {stamp}", bank_name="Test", account_no="1", ifsc="T0001", created_by="check_h5")
    bank_before = _bank_ledger_balance(bank.id)

    # --- unknown bank / unknown party are errors ---
    r_badbank = os.path.join(tmp, "badbank.xlsx")
    _write(r_badbank, "RECEIPTS", [["06-04-2026", cust, 100, "BANK", "No Such Bank", ""]])
    rep = svc.validate(svc.read_sheet(r_badbank, IMPORT_DEFS["RECEIPTS"].column_names()), "RECEIPTS")
    assert any("does not exist" in e["message"] and "Bank" in e["message"] for e in rep.errors), rep.errors

    r_ghost = os.path.join(tmp, "ghost.xlsx")
    _write(r_ghost, "RECEIPTS", [["06-04-2026", "Ghost Customer", 100, "CASH", "", ""]])
    rep = svc.validate(svc.read_sheet(r_ghost, IMPORT_DEFS["RECEIPTS"].column_names()), "RECEIPTS")
    assert any("Customer 'Ghost Customer' does not exist" in e["message"] for e in rep.errors), rep.errors
    print("Unknown bank account and unknown party are both errors")

    # --- receipt in full clears outstanding, raises bank ledger ---
    rf = os.path.join(tmp, "receipts.xlsx")
    _write(rf, "RECEIPTS", [["06-04-2026", cust, 1180, "BANK", bank.name, "UPI-1"]])
    log = svc.import_receipts(rf, "check_h5")
    assert log.status == "IMPORTED" and log.records_created == 1, (log.status, log.records_created)
    assert abs(_outstanding(cust)) < 0.01, f"customer outstanding not cleared: {_outstanding(cust)}"
    assert abs(_bank_ledger_balance(bank.id) - (bank_before + 1180)) < 0.01, _bank_ledger_balance(bank.id)
    print("Full receipt: customer outstanding -> 0, bank ledger +1180")

    # --- a receipt beyond what's owed WARNS (customer now at 0) ---
    rf2 = os.path.join(tmp, "receipts2.xlsx")
    _write(rf2, "RECEIPTS", [["07-04-2026", cust, 500, "CASH", "", ""]])
    rep = svc.validate(svc.read_sheet(rf2, IMPORT_DEFS["RECEIPTS"].column_names()), "RECEIPTS")
    assert rep.is_importable, "an over-receipt should be allowed (warn, not block)"
    assert any("credit" in w["message"] for w in rep.warnings), rep.warnings
    print("Receipt beyond outstanding is allowed but warns (balance would go credit)")

    # --- payment clears supplier outstanding ---
    payf = os.path.join(tmp, "pay.xlsx")
    _write(payf, "PAYMENTS", [["06-04-2026", supp, 590, "CASH", "", "CHQ-1"]])
    plog = svc.import_payments(payf, "check_h5")
    assert plog.status == "IMPORTED" and plog.records_created == 1
    assert abs(_outstanding(supp, suppliers=True)) < 0.01, f"supplier outstanding not cleared: {_outstanding(supp, suppliers=True)}"
    print("Payment: supplier outstanding -> 0")

    print("PASS")


if __name__ == "__main__":
    main()
