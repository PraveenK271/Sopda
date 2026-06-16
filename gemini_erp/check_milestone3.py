"""Milestone 3 check: create_invoice() in one transaction, with correct
stock deduction and GST split (CGST+SGST same state, IGST otherwise).

Run with: python check_milestone3.py
"""

from datetime import date
from decimal import Decimal

from database import get_session
from models import SalesInvoice, SalesInvoiceItem, StockTransaction
from services.customer_service import CustomerService
from services.item_service import ItemService
from services.sales_service import SalesService

ITEM_CODE = "CHK-M2-001"
SAME_STATE_INVOICE_NO = "CHK-M3-001"
OTHER_STATE_INVOICE_NO = "CHK-M3-002"


def get_or_create_customer(service, name, state, gstin):
    for c in service.list_customers():
        if c["name"] == name:
            return c
    customer = service.add_customer(name=name, gstin=gstin, state=state, address="Test Address")
    return {"id": customer.id, "name": customer.name, "state": customer.state}


def reset_invoice(session, invoice_no):
    """Remove a previous run's check invoice (and its lines/stock rows) so this script is repeatable."""
    existing = session.query(SalesInvoice).filter(SalesInvoice.invoice_no == invoice_no).first()
    if not existing:
        return
    session.query(StockTransaction).filter(
        StockTransaction.reference_type == "SALE", StockTransaction.reference_id == existing.id
    ).delete()
    session.query(SalesInvoiceItem).filter(SalesInvoiceItem.invoice_id == existing.id).delete()
    session.delete(existing)
    session.commit()


def main():
    item_service = ItemService()
    customer_service = CustomerService()
    sales_service = SalesService()

    items = {i["code"]: i for i in item_service.list_items()}
    item = items.get(ITEM_CODE)
    if item is None:
        raise SystemExit(f"Run check_milestone2.py first to create item {ITEM_CODE}")

    ap_customer = get_or_create_customer(customer_service, "Check AP Customer", "Andhra Pradesh", "37AAAAA0000A1Z5")
    ka_customer = get_or_create_customer(customer_service, "Check Karnataka Customer", "Karnataka", "29AAAAA0000A1Z5")

    session = get_session()
    reset_invoice(session, SAME_STATE_INVOICE_NO)
    reset_invoice(session, OTHER_STATE_INVOICE_NO)
    session.close()

    # --- Same state: CGST + SGST ---
    stock_before = item_service.get_current_stock(item["id"])
    print(f"Stock before: {stock_before}")

    invoice = sales_service.create_invoice(
        invoice_no=SAME_STATE_INVOICE_NO,
        invoice_date=date.today(),
        customer_id=ap_customer["id"],
        lines=[{"item_id": item["id"], "quantity": 10, "rate": 100}],
    )
    print(
        f"Invoice {invoice.invoice_no}: taxable={invoice.taxable_amount} "
        f"cgst={invoice.cgst} sgst={invoice.sgst} igst={invoice.igst} total={invoice.total}"
    )
    assert invoice.taxable_amount == Decimal("1000.00")
    assert invoice.cgst == Decimal("90.00")
    assert invoice.sgst == Decimal("90.00")
    assert invoice.igst == Decimal("0.00")
    assert invoice.total == Decimal("1180.00")

    stock_after = item_service.get_current_stock(item["id"])
    print(f"Stock after: {stock_after}")
    assert stock_after == stock_before - 10

    session = get_session()
    saved_invoice = session.query(SalesInvoice).filter(SalesInvoice.invoice_no == SAME_STATE_INVOICE_NO).one()
    saved_lines = session.query(SalesInvoiceItem).filter(SalesInvoiceItem.invoice_id == saved_invoice.id).all()
    saved_stock_txns = session.query(StockTransaction).filter(
        StockTransaction.reference_type == "SALE", StockTransaction.reference_id == saved_invoice.id
    ).all()
    assert len(saved_lines) == 1
    assert len(saved_stock_txns) == 1
    assert saved_stock_txns[0].type == "OUT"
    assert float(saved_stock_txns[0].quantity) == 10
    session.close()
    print("Invoice + line + stock_transaction rows all exist (same-state / CGST+SGST)")

    # --- Different state: IGST ---
    invoice2 = sales_service.create_invoice(
        invoice_no=OTHER_STATE_INVOICE_NO,
        invoice_date=date.today(),
        customer_id=ka_customer["id"],
        lines=[{"item_id": item["id"], "quantity": 5, "rate": 100}],
    )
    print(
        f"Invoice {invoice2.invoice_no}: taxable={invoice2.taxable_amount} "
        f"cgst={invoice2.cgst} sgst={invoice2.sgst} igst={invoice2.igst} total={invoice2.total}"
    )
    assert invoice2.taxable_amount == Decimal("500.00")
    assert invoice2.cgst == Decimal("0.00")
    assert invoice2.sgst == Decimal("0.00")
    assert invoice2.igst == Decimal("90.00")
    assert invoice2.total == Decimal("590.00")

    stock_final = item_service.get_current_stock(item["id"])
    print(f"Stock after second sale: {stock_final}")
    assert stock_final == stock_after - 5

    print("PASS")


if __name__ == "__main__":
    main()
