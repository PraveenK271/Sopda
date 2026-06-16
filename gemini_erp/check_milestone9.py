"""Milestone 9 check: purchase log lists invoices and shows their details.

Depends on the purchase invoices created by check_milestone7.py
(CHK-M7-001 / CHK-M7-002).
Run with: python check_milestone7.py  (first time only)
          python check_milestone9.py
"""

from decimal import Decimal

from services.purchase_service import PurchaseService

INVOICE_NOS = ["CHK-M7-001", "CHK-M7-002"]


def main():
    purchase_service = PurchaseService()

    invoices = {inv["invoice_no"]: inv for inv in purchase_service.list_purchase_invoices()}
    for invoice_no in INVOICE_NOS:
        if invoice_no not in invoices:
            raise SystemExit(f"Run check_milestone7.py first to create invoice {invoice_no}")

    inv1 = invoices["CHK-M7-001"]
    print(f"{inv1['invoice_no']}: {inv1['supplier_name']} total={inv1['total']}")
    assert inv1["supplier_name"] == "Check AP Supplier"
    assert Decimal(str(inv1["total"])) == Decimal("1180.00")

    details = purchase_service.get_purchase_invoice_details(inv1["id"])
    print(f"Lines: {details['lines']}")
    assert len(details["lines"]) == 1
    assert details["lines"][0]["item_code"] == "CHK-M2-001"
    assert Decimal(str(details["lines"][0]["amount"])) == Decimal("1000.00")
    assert Decimal(str(details["taxable_amount"])) == Decimal("1000.00")
    assert Decimal(str(details["cgst"])) == Decimal("90.00")
    assert Decimal(str(details["sgst"])) == Decimal("90.00")

    inv2 = invoices["CHK-M7-002"]
    print(f"{inv2['invoice_no']}: {inv2['supplier_name']} total={inv2['total']}")
    assert inv2["supplier_name"] == "Check Karnataka Supplier"
    assert Decimal(str(inv2["total"])) == Decimal("590.00")

    print("PASS")


if __name__ == "__main__":
    main()
