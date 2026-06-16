"""Milestone 7 check: create_purchase_invoice() in one transaction, with
correct stock addition and GST split (CGST+SGST same state, IGST otherwise).

This is the mirror image of check_milestone3.py - stock goes UP instead of
down, and stock_transactions get type='IN', reference_type='PURCHASE'.

Run with: python check_milestone7.py
"""

from datetime import date
from decimal import Decimal

from database import get_session
from models import PurchaseInvoice, PurchaseInvoiceItem, StockTransaction
from services.item_service import ItemService
from services.purchase_service import PurchaseService
from services.supplier_service import SupplierService

ITEM_CODE = "CHK-M2-001"
SAME_STATE_INVOICE_NO = "CHK-M7-001"
OTHER_STATE_INVOICE_NO = "CHK-M7-002"


def get_or_create_supplier(service, name, state, gstin):
    for s in service.list_suppliers():
        if s["name"] == name:
            return s
    supplier = service.add_supplier(name=name, gstin=gstin, state=state, address="Test Address")
    return {"id": supplier.id, "name": supplier.name, "state": supplier.state}


def reset_purchase_invoice(session, invoice_no):
    """Remove a previous run's check invoice (and its lines/stock rows) so this script is repeatable."""
    existing = session.query(PurchaseInvoice).filter(PurchaseInvoice.invoice_no == invoice_no).first()
    if not existing:
        return
    session.query(StockTransaction).filter(
        StockTransaction.reference_type == "PURCHASE", StockTransaction.reference_id == existing.id
    ).delete()
    session.query(PurchaseInvoiceItem).filter(PurchaseInvoiceItem.invoice_id == existing.id).delete()
    session.delete(existing)
    session.commit()


def main():
    item_service = ItemService()
    supplier_service = SupplierService()
    purchase_service = PurchaseService()

    items = {i["code"]: i for i in item_service.list_items()}
    item = items.get(ITEM_CODE)
    if item is None:
        raise SystemExit(f"Run check_milestone2.py first to create item {ITEM_CODE}")

    ap_supplier = get_or_create_supplier(supplier_service, "Check AP Supplier", "Andhra Pradesh", "37BBBBB0000B1Z5")
    ka_supplier = get_or_create_supplier(supplier_service, "Check Karnataka Supplier", "Karnataka", "29BBBBB0000B1Z5")

    session = get_session()
    reset_purchase_invoice(session, SAME_STATE_INVOICE_NO)
    reset_purchase_invoice(session, OTHER_STATE_INVOICE_NO)
    session.close()

    # --- Same state: CGST + SGST ---
    stock_before = item_service.get_current_stock(item["id"])
    print(f"Stock before: {stock_before}")

    invoice = purchase_service.create_purchase_invoice(
        invoice_no=SAME_STATE_INVOICE_NO,
        invoice_date=date.today(),
        supplier_id=ap_supplier["id"],
        lines=[{"item_id": item["id"], "quantity": 10, "rate": 100}],
    )
    print(
        f"Purchase {invoice.invoice_no}: taxable={invoice.taxable_amount} "
        f"cgst={invoice.cgst} sgst={invoice.sgst} igst={invoice.igst} total={invoice.total}"
    )
    assert invoice.taxable_amount == Decimal("1000.00")
    assert invoice.cgst == Decimal("90.00")
    assert invoice.sgst == Decimal("90.00")
    assert invoice.igst == Decimal("0.00")
    assert invoice.total == Decimal("1180.00")

    stock_after = item_service.get_current_stock(item["id"])
    print(f"Stock after: {stock_after}")
    assert stock_after == stock_before + 10

    session = get_session()
    saved_invoice = session.query(PurchaseInvoice).filter(PurchaseInvoice.invoice_no == SAME_STATE_INVOICE_NO).one()
    saved_lines = session.query(PurchaseInvoiceItem).filter(PurchaseInvoiceItem.invoice_id == saved_invoice.id).all()
    saved_stock_txns = session.query(StockTransaction).filter(
        StockTransaction.reference_type == "PURCHASE", StockTransaction.reference_id == saved_invoice.id
    ).all()
    assert len(saved_lines) == 1
    assert len(saved_stock_txns) == 1
    assert saved_stock_txns[0].type == "IN"
    assert float(saved_stock_txns[0].quantity) == 10
    session.close()
    print("Invoice + line + stock_transaction rows all exist (same-state / CGST+SGST)")

    # --- Different state: IGST ---
    invoice2 = purchase_service.create_purchase_invoice(
        invoice_no=OTHER_STATE_INVOICE_NO,
        invoice_date=date.today(),
        supplier_id=ka_supplier["id"],
        lines=[{"item_id": item["id"], "quantity": 5, "rate": 100}],
    )
    print(
        f"Purchase {invoice2.invoice_no}: taxable={invoice2.taxable_amount} "
        f"cgst={invoice2.cgst} sgst={invoice2.sgst} igst={invoice2.igst} total={invoice2.total}"
    )
    assert invoice2.taxable_amount == Decimal("500.00")
    assert invoice2.cgst == Decimal("0.00")
    assert invoice2.sgst == Decimal("0.00")
    assert invoice2.igst == Decimal("90.00")
    assert invoice2.total == Decimal("590.00")

    stock_final = item_service.get_current_stock(item["id"])
    print(f"Stock after second purchase: {stock_final}")
    assert stock_final == stock_after + 5

    print("PASS")


if __name__ == "__main__":
    main()
