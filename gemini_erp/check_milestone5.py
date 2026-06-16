"""Milestone 5 check: sales log lists invoices and shows their details.

Depends on the invoices created by check_milestone3.py (CHK-M3-001 / CHK-M3-002).
Run with: python check_milestone3.py  (first time only)
          python check_milestone5.py
"""

from decimal import Decimal

from services.sales_service import SalesService

INVOICE_NOS = ["CHK-M3-001", "CHK-M3-002"]


def main():
    sales_service = SalesService()

    invoices = {inv["invoice_no"]: inv for inv in sales_service.list_invoices()}
    for invoice_no in INVOICE_NOS:
        if invoice_no not in invoices:
            raise SystemExit(f"Run check_milestone3.py first to create invoice {invoice_no}")

    inv1 = invoices["CHK-M3-001"]
    print(f"{inv1['invoice_no']}: {inv1['customer_name']} total={inv1['total']}")
    assert inv1["customer_name"] == "Check AP Customer"
    assert Decimal(str(inv1["total"])) == Decimal("1180.00")

    details = sales_service.get_invoice_details(inv1["id"])
    print(f"Lines: {details['lines']}")
    assert len(details["lines"]) == 1
    assert details["lines"][0]["item_code"] == "CHK-M2-001"
    assert Decimal(str(details["lines"][0]["amount"])) == Decimal("1000.00")
    assert Decimal(str(details["taxable_amount"])) == Decimal("1000.00")
    assert Decimal(str(details["cgst"])) == Decimal("90.00")
    assert Decimal(str(details["sgst"])) == Decimal("90.00")

    inv2 = invoices["CHK-M3-002"]
    print(f"{inv2['invoice_no']}: {inv2['customer_name']} total={inv2['total']}")
    assert inv2["customer_name"] == "Check Karnataka Customer"
    assert Decimal(str(inv2["total"])) == Decimal("590.00")

    print("PASS")


if __name__ == "__main__":
    main()
