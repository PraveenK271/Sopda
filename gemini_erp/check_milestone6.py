"""Milestone 6 check: Supplier Master add + list.

Repeatable: re-uses the same supplier name, so re-running just confirms the
record (or a matching duplicate) is present.
"""

from services.supplier_service import SupplierService

SUPPLIER_NAME = "Check Supplier Pvt Ltd"


def main():
    supplier_service = SupplierService()

    existing = [s for s in supplier_service.list_suppliers() if s["name"] == SUPPLIER_NAME]
    if not existing:
        supplier_service.add_supplier(
            name=SUPPLIER_NAME,
            gstin="29ABCDE1234F1Z5",
            address="Industrial Area, Bengaluru",
            state="Karnataka",
        )

    suppliers = supplier_service.list_suppliers()
    match = next((s for s in suppliers if s["name"] == SUPPLIER_NAME), None)
    assert match is not None, "Supplier was not found after adding"
    print(f"Supplier: {match}")

    assert match["gstin"] == "29ABCDE1234F1Z5"
    assert match["state"] == "Karnataka"

    print("PASS")


if __name__ == "__main__":
    main()
