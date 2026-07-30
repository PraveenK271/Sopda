"""Milestone 16 check: Banking core — receipts & payments post to the books.

Self-contained fixtures (does NOT reuse/disturb the CHK-M11 fixtures that
check_milestone15.py asserts on):
  CHK-M16-CUST  — AP customer
  CHK-M16-SUPP  — AP supplier
  CHK-M16-ITEM  — item
  Sale     CHK-M16-SALE : 10 × 100 = 1000 taxable, 18% → total 1180
  Purchase CHK-M16-PURCH: 20 × 50  = 1000 taxable, 18% → total 1180
  Bank     CHK-M16-BANK : a bank account for the BANK-mode receipt path

Flow asserted:
  1. After the sale/purchase, customer & supplier each show 1180 outstanding.
  2. record_receipt(1180, CASH)  → customer outstanding drops to 0,
     Cash ledger Dr balance increases by 1180.
  3. record_payment(1180, CASH)  → supplier outstanding drops to 0,
     Cash ledger Dr balance decreases by 1180 (net Cash delta == 0).
  4. record_receipt(500, BANK)   → the bank account's ledger Dr balance
     increases by 500 (exercises the BANK path).

Repeatable: deletes its receipts/payments (+ journal entries) and the check
invoices each run.

Run with: ../venv/Scripts/python.exe check_milestone16.py
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import false, func, true

from database import get_session
from models import (
    JournalEntry,
    JournalEntryLine,
    LedgerAccount,
    Payment,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    Receipt,
    SalesInvoice,
    SalesInvoiceItem,
    StockTransaction,
)
from services.accounting_service import AccountingService
from services.banking_service import BankingService
from services.chart_of_accounts import CASH
from services.customer_service import CustomerService
from services.item_service import ItemService
from services.purchase_service import PurchaseService
from services.sales_service import SalesService
from services.supplier_service import SupplierService

CUSTOMER_NAME = "CHK-M16-CUST"
SUPPLIER_NAME = "CHK-M16-SUPP"
ITEM_CODE = "CHK-M16-ITEM"
SALE_INVOICE_NO = "CHK-M16-SALE"
PURCH_INVOICE_NO = "CHK-M16-PURCH"
BANK_NAME = "CHK-M16-BANK"

EXPECTED_TOTAL = 1180.00
BANK_RECEIPT = 500.00


def _get_or_create_customer(svc):
    for c in svc.list_customers():
        if c["name"] == CUSTOMER_NAME:
            return c
    obj = svc.add_customer(name=CUSTOMER_NAME, gstin="37CCCCC0000C1Z5", address="Test", state="Andhra Pradesh")
    return {"id": obj.id, "name": obj.name}


def _get_or_create_supplier(svc):
    for s in svc.list_suppliers():
        if s["name"] == SUPPLIER_NAME:
            return s
    obj = svc.add_supplier(name=SUPPLIER_NAME, gstin="37DDDDD0000D1Z5", address="Test", state="Andhra Pradesh")
    return {"id": obj.id, "name": obj.name}


def _get_or_create_item(svc):
    for i in svc.list_items():
        if i["code"] == ITEM_CODE:
            return i
    obj = svc.add_item(code=ITEM_CODE, name="CHK M16 Item", hsn_code="1234",
                       gst_rate=18, unit="PCS", opening_stock=100, reorder_level=5)
    return {"id": obj.id}


def _get_or_create_bank(svc):
    for b in svc.list_bank_accounts():
        if b["name"] == BANK_NAME:
            return b
    obj = svc.add_bank_account(name=BANK_NAME, bank_name="Test Bank", account_no="0001", ifsc="TEST0000001")
    return {"id": obj.id, "name": obj.name}


def _delete_journal_for(session, reference_type, reference_id):
    je = (
        session.query(JournalEntry)
        .filter(JournalEntry.reference_type == reference_type, JournalEntry.reference_id == reference_id)
        .first()
    )
    if je:
        session.query(JournalEntryLine).filter(JournalEntryLine.entry_id == je.id).delete()
        session.delete(je)


def _reset_receipts_payments(session, customer_id, supplier_id):
    for r in session.query(Receipt).filter(Receipt.customer_id == customer_id).all():
        _delete_journal_for(session, "RECEIPT", r.id)
        session.delete(r)
    for p in session.query(Payment).filter(Payment.supplier_id == supplier_id).all():
        _delete_journal_for(session, "PAYMENT", p.id)
        session.delete(p)
    session.commit()


def _delete_sale_invoice(session, invoice_no):
    inv = session.query(SalesInvoice).filter(SalesInvoice.invoice_no == invoice_no).first()
    if not inv:
        return
    _delete_journal_for(session, "SALE", inv.id)
    session.query(StockTransaction).filter(
        StockTransaction.reference_type == "SALE", StockTransaction.reference_id == inv.id
    ).delete()
    session.query(SalesInvoiceItem).filter(SalesInvoiceItem.invoice_id == inv.id).delete()
    session.delete(inv)
    session.commit()


def _delete_purchase_invoice(session, invoice_no):
    inv = session.query(PurchaseInvoice).filter(PurchaseInvoice.invoice_no == invoice_no).first()
    if not inv:
        return
    _delete_journal_for(session, "PURCHASE", inv.id)
    session.query(StockTransaction).filter(
        StockTransaction.reference_type == "PURCHASE", StockTransaction.reference_id == inv.id
    ).delete()
    session.query(PurchaseInvoiceItem).filter(PurchaseInvoiceItem.invoice_id == inv.id).delete()
    session.delete(inv)
    session.commit()


def _cash_dr_balance(session):
    """Net Dr balance on the Cash ledger account (opening + posted Dr - Cr)."""
    cash = AccountingService.get_account_by_code(session, CASH)
    dr, cr = (
        session.query(
            func.coalesce(func.sum(JournalEntryLine.debit), 0),
            func.coalesce(func.sum(JournalEntryLine.credit), 0),
        )
        .filter(JournalEntryLine.account_id == cash.id, JournalEntryLine.is_deleted == false())
        .one()
    )
    opening = float(cash.opening_balance)
    if cash.opening_balance_type == "Cr":
        opening = -opening
    return opening + float(dr) - float(cr)


def _ledger_dr_balance(session, account_id):
    dr, cr = (
        session.query(
            func.coalesce(func.sum(JournalEntryLine.debit), 0),
            func.coalesce(func.sum(JournalEntryLine.credit), 0),
        )
        .filter(JournalEntryLine.account_id == account_id, JournalEntryLine.is_deleted == false())
        .one()
    )
    acct = session.get(LedgerAccount, account_id)
    opening = float(acct.opening_balance)
    if acct.opening_balance_type == "Cr":
        opening = -opening
    return opening + float(dr) - float(cr)


def _outstanding_customer(name):
    row = next((c for c in AccountingService.get_outstanding_customers() if c["name"] == name), None)
    return row["outstanding"] if row else 0.0


def _outstanding_supplier(name):
    row = next((s for s in AccountingService.get_outstanding_suppliers() if s["name"] == name), None)
    return row["outstanding"] if row else 0.0


def main():
    customer = _get_or_create_customer(CustomerService())
    supplier = _get_or_create_supplier(SupplierService())
    item = _get_or_create_item(ItemService())
    banking = BankingService()
    bank = _get_or_create_bank(banking)

    # --- reset to a clean slate ---
    session = get_session()
    try:
        _reset_receipts_payments(session, customer["id"], supplier["id"])
        _delete_sale_invoice(session, SALE_INVOICE_NO)
        _delete_purchase_invoice(session, PURCH_INVOICE_NO)
        bank_ledger = (
            session.query(LedgerAccount).filter(LedgerAccount.bank_account_id == bank["id"]).first()
        )
        assert bank_ledger is not None, "Bank account has no linked ledger account"
        bank_ledger_id = bank_ledger.id
    finally:
        session.close()

    # --- create the sale & purchase that build up outstanding ---
    SalesService().create_invoice(
        invoice_no=SALE_INVOICE_NO, invoice_date=date.today(), customer_id=customer["id"],
        lines=[{"item_id": item["id"], "quantity": Decimal("10"), "rate": Decimal("100")}],
    )
    PurchaseService().create_purchase_invoice(
        invoice_no=PURCH_INVOICE_NO, invoice_date=date.today(), supplier_id=supplier["id"],
        lines=[{"item_id": item["id"], "quantity": Decimal("20"), "rate": Decimal("50")}],
    )

    # 1. Outstanding == invoice total before any receipt/payment.
    cust_out = _outstanding_customer(CUSTOMER_NAME)
    supp_out = _outstanding_supplier(SUPPLIER_NAME)
    assert abs(cust_out - EXPECTED_TOTAL) < 0.01, f"Customer outstanding {cust_out} != {EXPECTED_TOTAL}"
    assert abs(supp_out - EXPECTED_TOTAL) < 0.01, f"Supplier outstanding {supp_out} != {EXPECTED_TOTAL}"
    print(f"Before: customer outstanding {cust_out:,.2f}, supplier outstanding {supp_out:,.2f}")

    # --- snapshot Cash before ---
    session = get_session()
    try:
        cash_before = _cash_dr_balance(session)
        bank_before = _ledger_dr_balance(session, bank_ledger_id)
    finally:
        session.close()

    # 2. Receipt of full amount (CASH) -> customer outstanding to 0, Cash +1180.
    banking.record_receipt(
        date=date.today(), customer_id=customer["id"], amount=EXPECTED_TOTAL,
        payment_mode="CASH", reference_no="RV-M16-1", notes="full settlement",
    )
    cust_out = _outstanding_customer(CUSTOMER_NAME)
    assert abs(cust_out) < 0.01, f"Customer outstanding after receipt {cust_out} != 0"
    session = get_session()
    try:
        cash_after_receipt = _cash_dr_balance(session)
    finally:
        session.close()
    assert abs((cash_after_receipt - cash_before) - EXPECTED_TOTAL) < 0.01, \
        f"Cash delta after receipt {cash_after_receipt - cash_before} != {EXPECTED_TOTAL}"
    print(f"After CASH receipt: customer outstanding {cust_out:,.2f}, Cash +{cash_after_receipt - cash_before:,.2f}")

    # 3. Payment of full amount (CASH) -> supplier outstanding to 0, Cash -1180.
    banking.record_payment(
        date=date.today(), supplier_id=supplier["id"], amount=EXPECTED_TOTAL,
        payment_mode="CASH", reference_no="PV-M16-1", notes="full settlement",
    )
    supp_out = _outstanding_supplier(SUPPLIER_NAME)
    assert abs(supp_out) < 0.01, f"Supplier outstanding after payment {supp_out} != 0"
    session = get_session()
    try:
        cash_after_payment = _cash_dr_balance(session)
    finally:
        session.close()
    assert abs((cash_after_payment - cash_after_receipt) + EXPECTED_TOTAL) < 0.01, \
        f"Cash delta after payment {cash_after_payment - cash_after_receipt} != -{EXPECTED_TOTAL}"
    # Net Cash movement across receipt+payment should be zero.
    assert abs(cash_after_payment - cash_before) < 0.01, \
        f"Net Cash should be unchanged, got delta {cash_after_payment - cash_before}"
    print(f"After CASH payment: supplier outstanding {supp_out:,.2f}, Cash {cash_after_payment - cash_after_receipt:,.2f}")

    # 4. BANK-mode receipt -> bank account ledger increases.
    banking.record_receipt(
        date=date.today(), customer_id=customer["id"], amount=BANK_RECEIPT,
        payment_mode="BANK", bank_account_id=bank["id"], reference_no="RV-M16-2",
    )
    session = get_session()
    try:
        bank_after = _ledger_dr_balance(session, bank_ledger_id)
    finally:
        session.close()
    assert abs((bank_after - bank_before) - BANK_RECEIPT) < 0.01, \
        f"Bank ledger delta {bank_after - bank_before} != {BANK_RECEIPT}"
    # That BANK receipt put the customer into a 500 advance (Cr) balance.
    cust_out = _outstanding_customer(CUSTOMER_NAME)
    assert abs(cust_out) < 0.01, f"Customer should have no Dr outstanding (advance is Cr), got {cust_out}"
    print(f"After BANK receipt: bank '{BANK_NAME}' ledger +{bank_after - bank_before:,.2f}")

    print("PASS")


if __name__ == "__main__":
    main()
