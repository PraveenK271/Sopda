"""Milestone 15 check: Customer/Supplier Outstanding.

Depends on check_milestone11.py having been run (uses CHK-M11-* fixtures).
With no receipts/payments posted:
  CHK-M11-CUST outstanding == 1180.00 (sale total, Dr on customer ledger)
  CHK-M11-SUPP outstanding == 1180.00 (purchase total, Cr on supplier ledger)

Run with: python check_milestone15.py
"""

from services.accounting_service import AccountingService

CUSTOMER_NAME = "CHK-M11-CUST"
SUPPLIER_NAME = "CHK-M11-SUPP"
EXPECTED_OUTSTANDING = 1180.00


def main():
    customers = AccountingService.get_outstanding_customers()
    suppliers = AccountingService.get_outstanding_suppliers()

    cust = next((c for c in customers if c["name"] == CUSTOMER_NAME), None)
    assert cust is not None, (
        f"Customer {CUSTOMER_NAME} not in outstanding list — run check_milestone11.py first"
    )
    assert abs(cust["outstanding"] - EXPECTED_OUTSTANDING) < 0.01, \
        f"Customer outstanding {cust['outstanding']} != {EXPECTED_OUTSTANDING}"
    print(f"Customer '{cust['name']}' outstanding: {cust['outstanding']:,.2f}")

    supp = next((s for s in suppliers if s["name"] == SUPPLIER_NAME), None)
    assert supp is not None, (
        f"Supplier {SUPPLIER_NAME} not in outstanding list — run check_milestone11.py first"
    )
    assert abs(supp["outstanding"] - EXPECTED_OUTSTANDING) < 0.01, \
        f"Supplier outstanding {supp['outstanding']} != {EXPECTED_OUTSTANDING}"
    print(f"Supplier '{supp['name']}' outstanding: {supp['outstanding']:,.2f}")

    print(f"Total receivables: {sum(c['outstanding'] for c in customers):,.2f}")
    print(f"Total payables:    {sum(s['outstanding'] for s in suppliers):,.2f}")
    print("PASS")


if __name__ == "__main__":
    main()
