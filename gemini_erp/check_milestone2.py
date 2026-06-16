"""Milestone 2 check: add an item with opening stock 100 and confirm
get_current_stock / list_items report current stock = 100.

Run with: python check_milestone2.py
"""

from database import get_session
from models import Item
from services.item_service import ItemService

TEST_CODE = "CHK-M2-001"


def main():
    service = ItemService()

    # Remove a previous run's check item so this script is repeatable.
    session = get_session()
    existing = session.query(Item).filter(Item.code == TEST_CODE).first()
    if existing:
        session.delete(existing)
        session.commit()
    session.close()

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
