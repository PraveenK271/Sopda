"""H2 check: opening balances (as of 31-03-2026).

Asserts:
- set_opening_stock(item, 60) -> get_current_stock() == 60 with NO
  stock_transactions rows (opening stock is a baseline, not a movement)
- set a customer Dr 50,000 + a supplier Cr 30,000, post the opening journal ->
  the entry balances, and the Trial Balance total debit == total credit
- customer outstanding then shows 50,000 (counted ONCE, not doubled)
- posting the opening journal a second time raises

Runs on a DISPOSABLE database: post_opening_journal is a one-time GLOBAL
operation (and refuses to run twice), so this must NOT touch the production DB.
Point GEMINI_DB_URL at a throwaway SQLite file before running.

Run with: python check_h2.py
"""

from datetime import date, datetime

from database import DATABASE_URL, get_session
from models import JournalEntry, JournalEntryLine, StockTransaction
from services.accounting_service import AccountingService
from services.customer_service import CustomerService
from services.item_service import ItemService
from services.opening_balance_service import OpeningBalanceService
from services.supplier_service import SupplierService


def main():
    if "mssql" in DATABASE_URL:
        raise SystemExit(
            "Refusing to run against SQL Server: this posts a global opening "
            "journal. Point GEMINI_DB_URL at a throwaway SQLite file."
        )

    obs = OpeningBalanceService()
    stamp = datetime.now().strftime("%H%M%S%f")

    item = ItemService().add_item(code=f"H2-ITEM-{stamp}", name="H2 Item", unit="PCS",
                                  gst_rate=18, opening_stock=0, created_by="check_h2")
    cust = CustomerService().add_customer(name=f"H2 Cust {stamp}", state="Andhra Pradesh",
                                          created_by="check_h2")
    supp = SupplierService().add_supplier(name=f"H2 Supp {stamp}", state="Andhra Pradesh",
                                          created_by="check_h2")

    session = get_session()
    try:
        # 1. Opening stock = baseline, no movement.
        obs.set_opening_stock(session, item.id, 60, "check_h2")
        stock = ItemService().get_current_stock(item.id)
        assert stock == 60, f"expected stock 60, got {stock}"
        txn_count = (
            session.query(StockTransaction).filter(StockTransaction.item_id == item.id).count()
        )
        assert txn_count == 0, f"opening stock created {txn_count} stock_transactions (should be 0)"
        print("Opening stock 60 -> get_current_stock 60, no stock_transactions")

        # 2. Party balances + post the opening journal.
        obs.set_party_opening_balance(session, "CUSTOMER", cust.id, 50000, "Dr", "check_h2")
        obs.set_party_opening_balance(session, "SUPPLIER", supp.id, 30000, "Cr", "check_h2")
        entry = obs.post_opening_journal(session, date(2026, 3, 31), "check_h2")
        entry_id = entry.id
    finally:
        session.close()

    # The entry balances.
    session = get_session()
    try:
        lines = session.query(JournalEntryLine).filter(JournalEntryLine.entry_id == entry_id).all()
        dr = sum(float(l.debit) for l in lines)
        cr = sum(float(l.credit) for l in lines)
        assert abs(dr - cr) < 0.01, f"opening entry does not balance: Dr {dr} != Cr {cr}"
        # Dr customer 50k + Cr supplier 30k -> equity Cr 20k balances it.
        assert abs(dr - 50000) < 0.01, f"expected total Dr 50000, got {dr}"
    finally:
        session.close()
    print(f"Opening journal id={entry_id} balances (Dr {dr:.0f} == Cr {cr:.0f})")

    # Trial Balance balances.
    tb = AccountingService.get_trial_balance()
    total_debit = round(sum(r["debit"] for r in tb), 2)
    total_credit = round(sum(r["credit"] for r in tb), 2)
    assert abs(total_debit - total_credit) < 0.01, f"TB not balanced: {total_debit} vs {total_credit}"
    print(f"Trial Balance balanced: Dr {total_debit} == Cr {total_credit}")

    # Customer outstanding counted ONCE.
    outs = AccountingService.get_outstanding_customers()
    row = next((r for r in outs if r["customer_id"] == cust.id), None)
    assert row is not None and abs(row["outstanding"] - 50000) < 0.01, f"customer outstanding wrong: {row}"
    supp_out = AccountingService.get_outstanding_suppliers()
    srow = next((r for r in supp_out if r["supplier_id"] == supp.id), None)
    assert srow is not None and abs(srow["outstanding"] - 30000) < 0.01, f"supplier outstanding wrong: {srow}"
    print("Customer outstanding 50,000 and supplier outstanding 30,000 (single-counted)")

    # Second post refuses.
    session = get_session()
    try:
        obs.post_opening_journal(session, date(2026, 3, 31), "check_h2")
        raise AssertionError("second post_opening_journal did not raise")
    except ValueError:
        pass
    finally:
        session.close()
    print("Second post_opening_journal correctly refused")

    print("PASS")


if __name__ == "__main__":
    main()
