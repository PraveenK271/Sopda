"""Milestone 13 check: Trial Balance.

Depends on check_milestone11.py having been run (uses its CHK-M11-* fixtures).
After M11 fixtures:
  Sale CHK-M11-SALE:     taxable 1000, CGST 90, SGST 90, total 1180
  Purchase CHK-M11-PURCH: taxable 1000, CGST 90, SGST 90, total 1180

Expected trial balance (just from M11 fixtures, ignoring other data):
  Customer ledger (ASSET)    Dr 1180
  Supplier ledger (LIABILITY)  Cr 1180
  Sales Account (INCOME)       Cr 1000
  Purchase Account (EXPENSE)  Dr 1000
  CGST Output (LIABILITY)      Cr 90
  SGST Output (LIABILITY)      Cr 90
  CGST Input (ASSET)          Dr 90
  SGST Input (ASSET)          Dr 90

Sum Dr = sum Cr always (double-entry fundamental check).

Run with: python check_milestone13.py
"""

from database import get_session
from models import LedgerAccount, SalesInvoice
from services.accounting_service import AccountingService
from services.customer_service import CustomerService
from services.supplier_service import SupplierService

CUSTOMER_NAME = "CHK-M11-CUST"
SUPPLIER_NAME = "CHK-M11-SUPP"
SALE_INVOICE_NO = "CHK-M11-SALE"

EXPECTED_SALE_TAXABLE = 1000.0
EXPECTED_SALE_CGST = 90.0
EXPECTED_SALE_TOTAL = 1180.0
EXPECTED_PURCH_TAXABLE = 1000.0
EXPECTED_PURCH_CGST = 90.0
EXPECTED_PURCH_TOTAL = 1180.0


def main():
    session = get_session()
    try:
        sale_inv = (
            session.query(SalesInvoice)
            .filter(SalesInvoice.invoice_no == SALE_INVOICE_NO)
            .first()
        )
        assert sale_inv is not None, (
            f"Invoice {SALE_INVOICE_NO} not found — run check_milestone11.py first"
        )
        sale_date = sale_inv.date

        customer_svc = CustomerService()
        cust = next((c for c in customer_svc.list_customers() if c["name"] == CUSTOMER_NAME), None)
        assert cust is not None
        cust_ledger = (
            session.query(LedgerAccount).filter(LedgerAccount.customer_id == cust["id"]).first()
        )

        supplier_svc = SupplierService()
        supp = next((s for s in supplier_svc.list_suppliers() if s["name"] == SUPPLIER_NAME), None)
        assert supp is not None
        supp_ledger = (
            session.query(LedgerAccount).filter(LedgerAccount.supplier_id == supp["id"]).first()
        )

        sales_acct = AccountingService.get_account_by_code(session, "SALES")
        purchase_acct = AccountingService.get_account_by_code(session, "PURCHASE")
        cgst_out = AccountingService.get_account_by_code(session, "CGST_OUTPUT")
        cgst_in = AccountingService.get_account_by_code(session, "CGST_INPUT")
    finally:
        session.close()

    # --- Trial balance as of the sale date ---
    tb = AccountingService.get_trial_balance(sale_date)
    by_name = {r["account_name"]: r for r in tb}

    # 1. Fundamental check: total debit == total credit
    total_dr = sum(r["debit"] for r in tb)
    total_cr = sum(r["credit"] for r in tb)
    assert abs(total_dr - total_cr) < 0.01, \
        f"Trial balance does NOT balance: Dr={total_dr:.2f} Cr={total_cr:.2f}"
    print(f"Trial balance balanced: Dr={total_dr:,.2f} = Cr={total_cr:,.2f}")

    # 2. Customer ledger: Dr side (they owe us)
    cust_row = by_name.get(cust_ledger.name)
    assert cust_row is not None, f"Customer ledger '{cust_ledger.name}' missing from trial balance"
    assert cust_row["debit"] >= EXPECTED_SALE_TOTAL, \
        f"Customer Dr {cust_row['debit']} < expected {EXPECTED_SALE_TOTAL}"
    print(f"Customer '{cust_row['account_name']}': Dr {cust_row['debit']:,.2f}")

    # 3. Supplier ledger: Cr side (we owe them)
    supp_row = by_name.get(supp_ledger.name)
    assert supp_row is not None, f"Supplier ledger '{supp_ledger.name}' missing from trial balance"
    assert supp_row["credit"] >= EXPECTED_PURCH_TOTAL, \
        f"Supplier Cr {supp_row['credit']} < expected {EXPECTED_PURCH_TOTAL}"
    print(f"Supplier '{supp_row['account_name']}': Cr {supp_row['credit']:,.2f}")

    # 4. Sales Account: Cr side
    sales_row = by_name.get(sales_acct.name)
    assert sales_row is not None, "Sales Account missing from trial balance"
    assert sales_row["credit"] >= EXPECTED_SALE_TAXABLE
    print(f"Sales Account: Cr {sales_row['credit']:,.2f}")

    # 5. Purchase Account: Dr side
    purch_row = by_name.get(purchase_acct.name)
    assert purch_row is not None, "Purchase Account missing from trial balance"
    assert purch_row["debit"] >= EXPECTED_PURCH_TAXABLE
    print(f"Purchase Account: Dr {purch_row['debit']:,.2f}")

    # 6. CGST Output: Cr, CGST Input: Dr
    cgst_out_row = by_name.get(cgst_out.name)
    assert cgst_out_row is not None and cgst_out_row["credit"] >= EXPECTED_SALE_CGST
    print(f"CGST Output: Cr {cgst_out_row['credit']:,.2f}")

    cgst_in_row = by_name.get(cgst_in.name)
    assert cgst_in_row is not None and cgst_in_row["debit"] >= EXPECTED_PURCH_CGST
    print(f"CGST Input: Dr {cgst_in_row['debit']:,.2f}")

    print("PASS")


if __name__ == "__main__":
    main()
