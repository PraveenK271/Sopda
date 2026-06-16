"""Milestone 12 check: Day Book and Ledger view service methods.

Depends on check_milestone11.py having been run (uses its CHK-M11-* fixtures).

Run with: python check_milestone12.py
"""

from database import get_session
from models import LedgerAccount, SalesInvoice
from services.accounting_service import AccountingService
from services.customer_service import CustomerService

CUSTOMER_NAME = "CHK-M11-CUST"
SALE_INVOICE_NO = "CHK-M11-SALE"
PURCH_INVOICE_NO = "CHK-M11-PURCH"


def main():
    # --- Retrieve M11 fixture IDs ---
    session = get_session()
    try:
        sale_inv = (
            session.query(SalesInvoice)
            .filter(SalesInvoice.invoice_no == SALE_INVOICE_NO)
            .first()
        )
        assert sale_inv is not None, (
            f"Sale invoice {SALE_INVOICE_NO} not found — run check_milestone11.py first"
        )
        sale_date = sale_inv.date
        sale_total = float(sale_inv.total)
        sale_taxable = float(sale_inv.taxable_amount)
        sale_cgst = float(sale_inv.cgst)

        customer_svc = CustomerService()
        customers = [c for c in customer_svc.list_customers() if c["name"] == CUSTOMER_NAME]
        assert customers, f"Customer {CUSTOMER_NAME} not found"
        customer_id = customers[0]["id"]

        cust_ledger = (
            session.query(LedgerAccount)
            .filter(LedgerAccount.customer_id == customer_id)
            .first()
        )
        assert cust_ledger is not None, "Customer has no ledger account"
        cust_ledger_id = cust_ledger.id

        sales_acct = AccountingService.get_account_by_code(session, "SALES")
        sales_acct_id = sales_acct.id
    finally:
        session.close()

    # --- 1. Day Book includes the M11 sale entry ---
    day_book = AccountingService.get_day_book(sale_date, sale_date)
    sale_entries = [e for e in day_book if e["reference_type"] == "SALE" and e["reference_id"] == sale_inv.id]
    assert len(sale_entries) == 1, f"Expected 1 SALE entry for {SALE_INVOICE_NO} in day book, got {len(sale_entries)}"
    sale_entry = sale_entries[0]
    assert sale_entry["narration"] == f"Sales Invoice {SALE_INVOICE_NO}", \
        f"Narration mismatch: {sale_entry['narration']}"
    # Lines: Dr customer, Cr Sales, Cr CGST Output, Cr SGST Output
    assert len(sale_entry["lines"]) == 4, f"Expected 4 lines, got {len(sale_entry['lines'])}"
    total_dr = sum(l["debit"] for l in sale_entry["lines"])
    total_cr = sum(l["credit"] for l in sale_entry["lines"])
    assert abs(total_dr - total_cr) < 0.001, f"Day book entry not balanced: Dr={total_dr} Cr={total_cr}"
    print(f"Day Book: SALE entry found, {len(sale_entry['lines'])} lines, balanced (Dr={total_dr:.2f})")

    # --- 2. Day Book also includes the M11 purchase entry ---
    purchase_entries = [e for e in day_book if e["reference_type"] == "PURCHASE"]
    assert len(purchase_entries) >= 1, "Purchase entry missing from day book"
    print(f"Day Book: PURCHASE entry found")

    # --- 3. Sales Account ledger shows credit for the sale ---
    sales_ledger = AccountingService.get_ledger(sales_acct_id, sale_date, sale_date)
    assert sales_ledger["account_name"] == "Sales Account", \
        f"Account name: {sales_ledger['account_name']}"
    sale_line = next(
        (e for e in sales_ledger["entries"] if abs(e["credit"] - sale_taxable) < 0.001),
        None,
    )
    assert sale_line is not None, f"Sales Account: expected credit of {sale_taxable} not found"
    print(f"Sales Account ledger: credit {sale_line['credit']:.2f}, closing balance {sales_ledger['closing_balance']:.2f} {sales_ledger['closing_balance_type']}")

    # --- 4. Customer ledger shows debit for the sale and running balance ---
    cust_ledger_data = AccountingService.get_ledger(cust_ledger_id, sale_date, sale_date)
    sale_debit_line = next(
        (e for e in cust_ledger_data["entries"] if abs(e["debit"] - sale_total) < 0.001),
        None,
    )
    assert sale_debit_line is not None, f"Customer ledger: expected debit of {sale_total} not found"
    assert sale_debit_line["balance_type"] == "Dr", \
        f"Customer balance should be Dr, got {sale_debit_line['balance_type']}"
    print(
        f"Customer ledger: debit {sale_debit_line['debit']:.2f}, "
        f"balance {sale_debit_line['balance']:.2f} {sale_debit_line['balance_type']}"
    )

    # --- 5. list_accounts() returns all accounts including system + customer/supplier ones ---
    accounts = AccountingService.list_accounts()
    codes = {a["code"] for a in accounts if a["code"]}
    for expected_code in ("SALES", "PURCHASE", "CGST_OUTPUT", "SGST_OUTPUT"):
        assert expected_code in codes, f"list_accounts() missing {expected_code}"
    print(f"list_accounts(): {len(accounts)} accounts, system codes present")

    print("PASS")


if __name__ == "__main__":
    main()
