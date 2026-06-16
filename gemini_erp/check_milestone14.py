"""Milestone 14 check: Profit & Loss and Balance Sheet.

Depends on check_milestone11.py having been run (uses CHK-M11-* fixtures).
M11 fixtures (AP → AP, 18% GST):
  Sale CHK-M11-SALE:      taxable 1000, CGST 90, SGST 90, total 1180
  Purchase CHK-M11-PURCH: taxable 1000, CGST 90, SGST 90, total 1180

P&L from M11 fixtures only (ignoring other invoices in the DB):
  Income:  Sales Account = 1000  (Cr posted by M11 sale)
  Expense: Purchase Account = 1000  (Dr posted by M11 purchase)
  Net profit from M11 = 0

Balance Sheet identity:  sum(assets) == sum(liabilities) + net_profit_to_date

Run with: python check_milestone14.py
"""

from database import get_session
from models import SalesInvoice
from services.accounting_service import AccountingService

SALE_INVOICE_NO = "CHK-M11-SALE"


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
        test_date = sale_inv.date
    finally:
        session.close()

    # --- P&L for the fixture date ---
    pl = AccountingService.get_profit_and_loss(test_date, test_date)

    income_names = [r["account_name"] for r in pl["income"]]
    expense_names = [r["account_name"] for r in pl["expenses"]]
    assert any("Sales" in n for n in income_names), \
        f"Sales Account missing from income: {income_names}"
    assert any("Purchase" in n for n in expense_names), \
        f"Purchase Account missing from expenses: {expense_names}"

    sales_income = next(r["amount"] for r in pl["income"] if "Sales" in r["account_name"])
    purchase_expense = next(r["amount"] for r in pl["expenses"] if "Purchase" in r["account_name"])
    assert abs(sales_income - 1000.0) < 0.01, f"Sales income {sales_income} != 1000"
    assert abs(purchase_expense - 1000.0) < 0.01, f"Purchase expense {purchase_expense} != 1000"

    expected_net = sales_income - purchase_expense
    assert abs(pl["net_profit"] - expected_net) < 0.01, \
        f"net_profit {pl['net_profit']} != expected {expected_net}"
    print(f"P&L: income={sales_income:.2f}, expenses={purchase_expense:.2f}, net_profit={pl['net_profit']:.2f}")

    # --- Balance Sheet as of fixture date ---
    bs = AccountingService.get_balance_sheet(test_date)

    total_assets = sum(r["amount"] for r in bs["assets"])
    total_liab = sum(r["amount"] for r in bs["liabilities"])
    net_profit = bs["net_profit_to_date"]

    # Fundamental identity: assets == liabilities + net_profit_to_date
    diff = abs(total_assets - (total_liab + net_profit))
    assert diff < 0.01, (
        f"Balance sheet does not balance: assets={total_assets:.2f}, "
        f"liabilities={total_liab:.2f}, net_profit={net_profit:.2f}, diff={diff:.2f}"
    )
    print(
        f"Balance Sheet: assets={total_assets:,.2f}, "
        f"liabilities={total_liab:,.2f}, "
        f"net_profit_to_date={net_profit:,.2f} -- BALANCED"
    )

    print("PASS")


if __name__ == "__main__":
    main()
