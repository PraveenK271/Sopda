"""Milestone 10 check: Chart of Accounts foundation.

Repeatable: re-uses the same customer/supplier names, so re-running just
confirms the records (and their linked ledger accounts) are present.
"""

from database import get_session
from models import LedgerAccount
from services.accounting_service import AccountingService
from services.chart_of_accounts import SYSTEM_ACCOUNTS, ensure_system_accounts
from services.customer_service import CustomerService
from services.supplier_service import SupplierService

CUSTOMER_NAME = "Check M10 Customer"
SUPPLIER_NAME = "Check M10 Supplier"


def main():
    session = get_session()
    try:
        # Idempotency: run twice, count of system accounts must not grow.
        ensure_system_accounts(session)
        ensure_system_accounts(session)
        system_count = (
            session.query(LedgerAccount)
            .filter(LedgerAccount.code.isnot(None))
            .count()
        )
        assert system_count == len(SYSTEM_ACCOUNTS), (
            f"Expected {len(SYSTEM_ACCOUNTS)} system accounts, found {system_count}"
        )
        print(f"System accounts OK: {system_count}")

        sales_account = AccountingService.get_account_by_code(session, "SALES")
        assert sales_account.account_type == "INCOME"
        assert sales_account.account_group == "Sales Accounts"
        print(f"SALES account: {sales_account.name} ({sales_account.account_type})")

        try:
            AccountingService.get_account_by_code(session, "NOT_A_CODE")
            raise AssertionError("Expected ValueError for unknown code")
        except ValueError:
            print("Unknown code correctly raises ValueError")
    finally:
        session.close()

    customer_service = CustomerService()
    customers = [c for c in customer_service.list_customers() if c["name"] == CUSTOMER_NAME]
    if not customers:
        customer_service.add_customer(
            name=CUSTOMER_NAME, gstin=None, address="Test Address", state="Andhra Pradesh"
        )
        customers = [c for c in customer_service.list_customers() if c["name"] == CUSTOMER_NAME]
    customer_id = customers[0]["id"]

    session = get_session()
    try:
        customer_ledger = (
            session.query(LedgerAccount).filter(LedgerAccount.customer_id == customer_id).first()
        )
        assert customer_ledger is not None, "Customer has no linked ledger account"
        assert customer_ledger.account_group == "Sundry Debtors"
        assert customer_ledger.account_type == "ASSET"
        print(f"Customer ledger account OK: {customer_ledger.name} ({customer_ledger.account_group})")
    finally:
        session.close()

    supplier_service = SupplierService()
    suppliers = [s for s in supplier_service.list_suppliers() if s["name"] == SUPPLIER_NAME]
    if not suppliers:
        supplier_service.add_supplier(
            name=SUPPLIER_NAME, gstin=None, address="Test Address", state="Karnataka"
        )
        suppliers = [s for s in supplier_service.list_suppliers() if s["name"] == SUPPLIER_NAME]
    supplier_id = suppliers[0]["id"]

    session = get_session()
    try:
        supplier_ledger = (
            session.query(LedgerAccount).filter(LedgerAccount.supplier_id == supplier_id).first()
        )
        assert supplier_ledger is not None, "Supplier has no linked ledger account"
        assert supplier_ledger.account_group == "Sundry Creditors"
        assert supplier_ledger.account_type == "LIABILITY"
        print(f"Supplier ledger account OK: {supplier_ledger.name} ({supplier_ledger.account_group})")
    finally:
        session.close()

    print("PASS")


if __name__ == "__main__":
    main()
