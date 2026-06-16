"""Check: inline "Add New Item" from the Purchase screen.

The AddItemDialog calls ItemService.add_item() directly - the same service
the Items page uses - so this script exercises that shared path:
1. add_item() creates exactly one items row.
2. The item then appears via list_items(), same as on the Items page.
3. A duplicate item code is rejected (shared validation).
4. Recording a purchase for the new item writes an IN stock_transaction, so
   its current stock equals the purchased quantity (opening_stock is 0).

Repeatable: re-uses the same item code / supplier / invoice number.

Run with: python check_inline_item.py
"""

from datetime import date
from decimal import Decimal

from database import get_session
from models import PurchaseInvoice, PurchaseInvoiceItem, StockTransaction
from services.item_service import ItemService
from services.purchase_service import PurchaseService
from services.supplier_service import SupplierService

ITEM_CODE = "CHK-INLINE-001"
SUPPLIER_NAME = "Check Inline Supplier"
INVOICE_NO = "CHK-INLINE-001"
QUANTITY = Decimal("7")


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
    purchase_service = PurchaseService()
    supplier_service = SupplierService()

    # 1. add_item() (what AddItemDialog calls) creates exactly one items row.
    existing_item = next((i for i in item_service.list_items() if i["code"] == ITEM_CODE), None)
    if existing_item is None:
        item = item_service.add_item(
            code=ITEM_CODE,
            name="Check Inline Item",
            hsn_code="9999",
            gst_rate=18,
            unit="PCS",
            opening_stock=0,
            reorder_level=5,
        )
        item_id = item.id
    else:
        item_id = existing_item["id"]

    matching = [i for i in item_service.list_items() if i["code"] == ITEM_CODE]
    assert len(matching) == 1, f"Expected exactly one item with code {ITEM_CODE}, found {len(matching)}"
    print(f"Item via ItemService.add_item(): {matching[0]}")

    # 2. Duplicate code is rejected - shared by Items page and the dialog.
    try:
        item_service.add_item(code=ITEM_CODE, name="Duplicate")
        raise AssertionError("Expected ValueError for duplicate item code")
    except ValueError:
        print("Duplicate item code correctly rejected")

    # 3. The item appears on the Items page (list_items()) - same data.
    assert any(i["code"] == ITEM_CODE for i in item_service.list_items())

    # 4. Recording a purchase writes an IN stock_transaction; current stock
    # equals the purchased quantity (opening_stock is 0).
    supplier = get_or_create_supplier(supplier_service, SUPPLIER_NAME, "Andhra Pradesh", "37CCCCC0000C1Z5")

    session = get_session()
    reset_purchase_invoice(session, INVOICE_NO)
    session.close()

    purchase_service.create_purchase_invoice(
        invoice_no=INVOICE_NO,
        invoice_date=date.today(),
        supplier_id=supplier["id"],
        lines=[{"item_id": item_id, "quantity": QUANTITY, "rate": Decimal("50")}],
    )

    current_stock = item_service.get_current_stock(item_id)
    print(f"Current stock after purchase: {current_stock}")
    assert current_stock == float(QUANTITY)

    print("PASS")


if __name__ == "__main__":
    main()
