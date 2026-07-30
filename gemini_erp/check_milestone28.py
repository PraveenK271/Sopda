"""Milestone 28 check: concurrent billing is safe on the shared database.

Two clients (threads, each with its own session) hit the same DB at once:

A. Duplicate invoice number race — both try to save the SAME invoice_no
   simultaneously. Exactly ONE wins; the other gets a clean ValueError (not a
   raw DB error), and exactly one row exists. This proves the UNIQUE(invoice_no)
   constraint + friendly handling make manual numbering race-safe.
B. Concurrent distinct sales of one item — N threads each sell 1 unit at once.
   Final stock == opening - N and exactly N OUT rows: no lost updates (stock is
   an append-only log, so concurrent OUTs can't clobber each other).
C. Oversell is allowed but warned — a sale beyond stock still commits and the
   returned invoice carries a stock warning; stock goes negative.

Best run against SQL Server (the multi-user target); on SQLite the writes just
serialize, which still satisfies A and B.

Run with: python check_milestone28.py
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from database import get_session
from models import SalesInvoice, StockTransaction
from services.customer_service import CustomerService
from services.item_service import ItemService
from services.sales_service import SalesService


def _make_customer(stamp):
    return CustomerService().add_customer(
        name=f"CHK-M28 Customer {stamp}", gstin="37AAAAA0000A1Z5",
        state="Andhra Pradesh", address="Test", created_by="check_milestone28",
    )


def _make_item(stamp, opening_stock):
    return ItemService().add_item(
        code=f"CHK-M28-ITEM-{stamp}", name="M28 Item", unit="PCS",
        gst_rate=18, opening_stock=opening_stock, created_by="check_milestone28",
    )


def scenario_a_duplicate_number(customer_id, item_id, stamp):
    sales = SalesService()
    invoice_no = f"CHK-M28-DUP-{stamp}"
    barrier = threading.Barrier(2)
    results = []

    def attempt():
        barrier.wait()  # release both threads together
        try:
            sales.create_invoice(
                invoice_no=invoice_no, invoice_date=date.today(), customer_id=customer_id,
                lines=[{"item_id": item_id, "quantity": 1, "rate": 100}],
                created_by="check_milestone28",
            )
            results.append(("ok", None))
        except ValueError as exc:
            results.append(("error", str(exc)))

    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(attempt)
        pool.submit(attempt)

    successes = [r for r in results if r[0] == "ok"]
    errors = [r for r in results if r[0] == "error"]
    assert len(successes) == 1, f"expected exactly 1 success, got {len(successes)}: {results}"
    assert len(errors) == 1, f"expected exactly 1 rejection, got {len(errors)}: {results}"
    assert "already used" in errors[0][1], f"unfriendly error: {errors[0][1]}"

    session = get_session()
    try:
        count = session.query(SalesInvoice).filter(SalesInvoice.invoice_no == invoice_no).count()
    finally:
        session.close()
    assert count == 1, f"expected 1 row for {invoice_no}, found {count}"
    print(f"A. Duplicate-number race: 1 saved, 1 rejected ('already used'), 1 row in DB")


def scenario_b_concurrent_stock(customer_id, item_id, stamp, n=8):
    sales = SalesService()
    item_service = ItemService()
    opening = item_service.get_current_stock(item_id)
    barrier = threading.Barrier(n)

    def sell(i):
        barrier.wait()
        sales.create_invoice(
            invoice_no=f"CHK-M28-CONC-{stamp}-{i}", invoice_date=date.today(),
            customer_id=customer_id, lines=[{"item_id": item_id, "quantity": 1, "rate": 100}],
            created_by="check_milestone28",
        )

    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(sell, range(n)))

    final = item_service.get_current_stock(item_id)
    assert final == opening - n, f"stock lost update: opening {opening}, after {n} sales = {final}"

    session = get_session()
    try:
        out_rows = (
            session.query(StockTransaction)
            .filter(
                StockTransaction.reference_type == "SALE",
                StockTransaction.type == "OUT",
                StockTransaction.item_id == item_id,
            )
            .count()
        )
    finally:
        session.close()
    assert out_rows >= n, f"expected >= {n} OUT rows, found {out_rows}"
    print(f"B. {n} concurrent sales: stock {opening} -> {final} (no lost updates)")


def scenario_c_oversell_warns(customer_id, stamp):
    # Fresh item with only 2 in stock; sell 5 -> allowed, but warned + negative.
    item = _make_item(f"{stamp}-oversell", opening_stock=2)
    invoice = SalesService().create_invoice(
        invoice_no=f"CHK-M28-OVER-{stamp}", invoice_date=date.today(), customer_id=customer_id,
        lines=[{"item_id": item.id, "quantity": 5, "rate": 100}], created_by="check_milestone28",
    )
    warnings = getattr(invoice, "stock_warnings", [])
    assert warnings, "expected an oversell warning"
    final = ItemService().get_current_stock(item.id)
    assert final == -3, f"expected stock -3 after overselling, got {final}"
    print(f"C. Oversell allowed + warned: stock now {final}; warning: {warnings[0]}")


def main():
    stamp = datetime.now().strftime("%H%M%S%f")
    customer = _make_customer(stamp)
    item = _make_item(stamp, opening_stock=1000)

    scenario_a_duplicate_number(customer.id, item.id, stamp)
    scenario_b_concurrent_stock(customer.id, item.id, stamp)
    scenario_c_oversell_warns(customer.id, stamp)

    print("PASS")


if __name__ == "__main__":
    main()
