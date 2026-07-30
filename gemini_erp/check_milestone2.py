"""Milestone 2 check: add an item with opening stock 100 and confirm
get_current_stock AND list_items both report current stock = 100.

Run with: python check_milestone2.py
"""

from datetime import datetime

from services.item_service import ItemService

# A unique code per run keeps this check idempotent without ever deleting rows.
# (The earlier version hard-deleted a fixed-code item on each run, which both
# broke the soft-delete rule and failed on SQL Server when the item was already
# referenced by invoice lines. A fresh item has no stock movements, so its
# current stock is exactly its opening stock.)
TEST_CODE = f"CHK-M2-{datetime.now():%Y%m%d%H%M%S}"


def main():
    service = ItemService()

    item = service.add_item(
        code=TEST_CODE,
        name="Milestone 2 Check Item",
        unit="PCS",
        gst_rate=18,
        opening_stock=100,
        reorder_level=10,
    )
    print(f"Added item {item.code} (id={item.id}) with opening_stock=100")

    current_stock = service.get_current_stock(item.id)
    print(f"get_current_stock -> {current_stock}")
    assert current_stock == 100, f"Expected 100, got {current_stock}"

    items = service.list_items()
    listed = next(i for i in items if i["id"] == item.id)
    print(f"list_items current_stock -> {listed['current_stock']}")
    assert listed["current_stock"] == 100, f"Expected 100, got {listed['current_stock']}"

    print("PASS")


if __name__ == "__main__":
    main()
