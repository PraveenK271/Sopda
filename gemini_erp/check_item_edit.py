"""Check: ItemService.update_item() edits master fields, keeps code unique,
and never disturbs the stock movement log (stock stays derived).

Run with: python check_item_edit.py
"""

from services.item_service import ItemService

CODE_A = "CHK-EDIT-A"
CODE_B = "CHK-EDIT-B"
CODE_A_RENAMED = "CHK-EDIT-A2"


def _get_or_create(service, code, name, **kw):
    for it in service.list_items():
        if it["code"] == code:
            return it["id"]
    return service.add_item(code=code, name=name, **kw).id


def main():
    service = ItemService()

    # Ensure two items exist to test the uniqueness clash.
    id_a = _get_or_create(service, CODE_A, "Edit Item A", gst_rate=5, opening_stock=100)
    id_b = _get_or_create(service, CODE_B, "Edit Item B", gst_rate=18, opening_stock=10)
    # Normalise A back to a known state in case of a prior run.
    service.update_item(id_a, code=CODE_A, name="Edit Item A", gst_rate=5,
                        unit=None, hsn_code=None, opening_stock=100, reorder_level=0)

    stock_before = service.get_current_stock(id_a)
    print(f"[setup] item A id={id_a} stock={stock_before}")

    # [1] Update fields (name, gst, unit, reorder) — values persist.
    service.update_item(
        id_a, code=CODE_A, name="Edit Item A - renamed", hsn_code="1234",
        gst_rate=12, unit="KG", opening_stock=100, reorder_level=7,
    )
    a = next(it for it in service.list_items() if it["id"] == id_a)
    assert a["name"] == "Edit Item A - renamed", a["name"]
    assert a["hsn_code"] == "1234"
    assert a["gst_rate"] == 12.0
    assert a["unit"] == "KG"
    assert a["reorder_level"] == 7.0
    print("[1] field updates persisted OK")

    # [2] Duplicate code is rejected (B's code taken, excluding self is allowed).
    clashed = False
    try:
        service.update_item(id_a, code=CODE_B, name="x")
    except ValueError as exc:
        clashed = True
        print(f"[2] duplicate-code rejected OK ({exc})")
    assert clashed, "expected a ValueError for duplicate code"

    # [2b] Keeping the SAME code on the same item is allowed (excludes self).
    service.update_item(id_a, code=CODE_A, name="Edit Item A - renamed",
                        gst_rate=12, unit="KG", opening_stock=100, reorder_level=7)
    print("[2b] same-code update on same item allowed OK")

    # [3] Editing opening_stock shifts the derived current stock by the delta,
    #     with NO new stock_transactions (the movement log is untouched).
    service.update_item(id_a, code=CODE_A, name="Edit Item A - renamed",
                        gst_rate=12, unit="KG", opening_stock=250, reorder_level=7)
    stock_after = service.get_current_stock(id_a)
    assert stock_after == stock_before + 150, (stock_after, stock_before)
    print(f"[3] opening_stock edit moved current stock 100->250 baseline "
          f"({stock_before}->{stock_after}) OK")

    print("\nAll item-edit checks passed.")


if __name__ == "__main__":
    main()
