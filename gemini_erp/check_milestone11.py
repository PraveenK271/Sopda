"""Milestone 11 check: accounting engine auto-posts journal entries for Sales & Purchase.

Creates:
  CHK-M11-CUST  — AP customer  (same state → CGST + SGST on the sale)
  CHK-M11-SUPP  — AP supplier  (same state → CGST + SGST on the purchase)
  CHK-M11-ITEM  — item used in both transactions
  Sale    invoice CHK-M11-SALE  : 10 units × 100 = 1000 taxable, 18% GST → CGST 90 SGST 90, total 1180
  Purchase invoice CHK-M11-PURCH: 20 units × 50  = 1000 taxable, 18% GST → CGST 90 SGST 90, total 1180

Repeatable: deletes the check invoices (and their journal entries) each run.

Run with: python check_milestone11.py
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import false, func, true

from database import get_session
from models import (
    JournalEntry,
    JournalEntryLine,
    LedgerAccount,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    SalesInvoice,
    SalesInvoiceItem,
    StockTransaction,
)
from services.accounting_service import AccountingService
from services.customer_service import CustomerService
from services.item_service import ItemService
from services.purchase_service import PurchaseService
from services.sales_service import SalesService
from services.supplier_service import SupplierService

CUSTOMER_NAME = "CHK-M11-CUST"
SUPPLIER_NAME = "CHK-M11-SUPP"
ITEM_CODE = "CHK-M11-ITEM"
SALE_INVOICE_NO = "CHK-M11-SALE"
PURCH_INVOICE_NO = "CHK-M11-PURCH"

SALE_QTY = Decimal("10")
SALE_RATE = Decimal("100")
PURCH_QTY = Decimal("20")
PURCH_RATE = Decimal("50")
GST_RATE = 18  # %  → CGST 9% + SGST 9% (AP → AP)


def _get_or_create_customer(svc):
    for c in svc.list_customers():
        if c["name"] == CUSTOMER_NAME:
            return c
    obj = svc.add_customer(
        name=CUSTOMER_NAME, gstin="37AAAAA0000A1Z5", address="Test", state="Andhra Pradesh"
    )
    return {"id": obj.id, "name": obj.name}


def _get_or_create_supplier(svc):
    for s in svc.list_suppliers():
        if s["name"] == SUPPLIER_NAME:
            return s
    obj = svc.add_supplier(
        name=SUPPLIER_NAME, gstin="37BBBBB0000B1Z5", address="Test", state="Andhra Pradesh"
    )
    return {"id": obj.id, "name": obj.name}


def _get_or_create_item(svc):
    for i in svc.list_items():
        if i["code"] == ITEM_CODE:
            return i
    obj = svc.add_item(
        code=ITEM_CODE, name="CHK M11 Item", hsn_code="1234",
        gst_rate=GST_RATE, unit="PCS", opening_stock=100, reorder_level=5,
    )
    return {"id": obj.id}


def _delete_sale_invoice(session, invoice_no):
    inv = session.query(SalesInvoice).filter(SalesInvoice.invoice_no == invoice_no).first()
    if not inv:
        return
    # delete journal entry lines + entry
    jentry = (
        session.query(JournalEntry)
        .filter(JournalEntry.reference_type == "SALE", JournalEntry.reference_id == inv.id)
        .first()
    )
    if jentry:
        session.query(JournalEntryLine).filter(JournalEntryLine.entry_id == jentry.id).delete()
        session.delete(jentry)
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
    jentry = (
        session.query(JournalEntry)
        .filter(JournalEntry.reference_type == "PURCHASE", JournalEntry.reference_id == inv.id)
        .first()
    )
    if jentry:
        session.query(JournalEntryLine).filter(JournalEntryLine.entry_id == jentry.id).delete()
        session.delete(jentry)
    session.query(StockTransaction).filter(
        StockTransaction.reference_type == "PURCHASE", StockTransaction.reference_id == inv.id
    ).delete()
    session.query(PurchaseInvoiceItem).filter(PurchaseInvoiceItem.invoice_id == inv.id).delete()
    session.delete(inv)
    session.commit()


def _account_balance(session, account_id):
    """Returns (total_debit, total_credit) posted to an account across all journal entry lines."""
    dr, cr = (
        session.query(
            func.coalesce(func.sum(JournalEntryLine.debit), 0),
            func.coalesce(func.sum(JournalEntryLine.credit), 0),
        )
        .filter(JournalEntryLine.account_id == account_id, JournalEntryLine.is_deleted == false())
        .one()
    )
    return float(dr), float(cr)


def main():
    customer_svc = CustomerService()
    supplier_svc = SupplierService()
    item_svc = ItemService()
    sales_svc = SalesService()
    purchase_svc = PurchaseService()

    customer = _get_or_create_customer(customer_svc)
    supplier = _get_or_create_supplier(supplier_svc)
    item = _get_or_create_item(item_svc)

    session = get_session()
    try:
        _delete_sale_invoice(session, SALE_INVOICE_NO)
        _delete_purchase_invoice(session, PURCH_INVOICE_NO)

        # Snapshot account balances BEFORE posting so we can measure the delta.
        cust_ledger = (
            session.query(LedgerAccount)
            .filter(LedgerAccount.customer_id == customer["id"])
            .first()
        )
        assert cust_ledger is not None, "Customer has no ledger account"
        supp_ledger = (
            session.query(LedgerAccount)
            .filter(LedgerAccount.supplier_id == supplier["id"])
            .first()
        )
        assert supp_ledger is not None, "Supplier has no ledger account"

        sales_acct = AccountingService.get_account_by_code(session, "SALES")
        cgst_out = AccountingService.get_account_by_code(session, "CGST_OUTPUT")
        sgst_out = AccountingService.get_account_by_code(session, "SGST_OUTPUT")
        purchase_acct = AccountingService.get_account_by_code(session, "PURCHASE")
        cgst_in = AccountingService.get_account_by_code(session, "CGST_INPUT")
        sgst_in = AccountingService.get_account_by_code(session, "SGST_INPUT")

        before = {
            "cust_dr": _account_balance(session, cust_ledger.id)[0],
            "sales_cr": _account_balance(session, sales_acct.id)[1],
            "cgst_out_cr": _account_balance(session, cgst_out.id)[1],
            "sgst_out_cr": _account_balance(session, sgst_out.id)[1],
            "supp_cr": _account_balance(session, supp_ledger.id)[1],
            "purchase_dr": _account_balance(session, purchase_acct.id)[0],
            "cgst_in_dr": _account_balance(session, cgst_in.id)[0],
            "sgst_in_dr": _account_balance(session, sgst_in.id)[0],
        }
    finally:
        session.close()

    # --- Post sale ---
    sale_inv = sales_svc.create_invoice(
        invoice_no=SALE_INVOICE_NO,
        invoice_date=date.today(),
        customer_id=customer["id"],
        lines=[{"item_id": item["id"], "quantity": SALE_QTY, "rate": SALE_RATE}],
    )
    expected_sale_taxable = (SALE_QTY * SALE_RATE).quantize(Decimal("0.01"))
    expected_sale_cgst = (expected_sale_taxable * Decimal("9") / 100).quantize(Decimal("0.01"))
    expected_sale_sgst = expected_sale_cgst
    expected_sale_total = expected_sale_taxable + expected_sale_cgst + expected_sale_sgst

    print(f"Sale invoice {sale_inv.invoice_no}: taxable={sale_inv.taxable_amount} total={sale_inv.total}")

    # --- Post purchase ---
    purch_inv = purchase_svc.create_purchase_invoice(
        invoice_no=PURCH_INVOICE_NO,
        invoice_date=date.today(),
        supplier_id=supplier["id"],
        lines=[{"item_id": item["id"], "quantity": PURCH_QTY, "rate": PURCH_RATE}],
    )
    expected_purch_taxable = (PURCH_QTY * PURCH_RATE).quantize(Decimal("0.01"))
    expected_purch_cgst = (expected_purch_taxable * Decimal("9") / 100).quantize(Decimal("0.01"))
    expected_purch_sgst = expected_purch_cgst
    expected_purch_total = expected_purch_taxable + expected_purch_cgst + expected_purch_sgst

    print(f"Purchase invoice {purch_inv.invoice_no}: taxable={purch_inv.taxable_amount} total={purch_inv.total}")

    # --- Assertions ---
    session = get_session()
    try:
        # 1. Both journal entries exist and are balanced.
        sale_je = (
            session.query(JournalEntry)
            .filter(JournalEntry.reference_type == "SALE", JournalEntry.reference_id == sale_inv.id)
            .first()
        )
        assert sale_je is not None, "Sale journal entry missing"
        sale_lines = session.query(JournalEntryLine).filter(JournalEntryLine.entry_id == sale_je.id).all()
        assert sum(float(l.debit) for l in sale_lines) == sum(float(l.credit) for l in sale_lines), \
            "Sale journal entry does not balance"
        print(f"Sale journal entry OK: {len(sale_lines)} lines, balanced")

        purch_je = (
            session.query(JournalEntry)
            .filter(JournalEntry.reference_type == "PURCHASE", JournalEntry.reference_id == purch_inv.id)
            .first()
        )
        assert purch_je is not None, "Purchase journal entry missing"
        purch_lines = session.query(JournalEntryLine).filter(JournalEntryLine.entry_id == purch_je.id).all()
        assert sum(float(l.debit) for l in purch_lines) == sum(float(l.credit) for l in purch_lines), \
            "Purchase journal entry does not balance"
        print(f"Purchase journal entry OK: {len(purch_lines)} lines, balanced")

        # 2. Customer ledger account debit increased by sale total.
        after_cust_dr = _account_balance(session, cust_ledger.id)[0]
        delta_cust = after_cust_dr - before["cust_dr"]
        assert abs(delta_cust - float(expected_sale_total)) < 0.001, \
            f"Customer ledger debit delta {delta_cust} != expected {expected_sale_total}"
        print(f"Customer ledger debit +{delta_cust:.2f} (expected {expected_sale_total})")

        # 3. Sales Account credit increased by taxable amount.
        after_sales_cr = _account_balance(session, sales_acct.id)[1]
        delta_sales = after_sales_cr - before["sales_cr"]
        assert abs(delta_sales - float(expected_sale_taxable)) < 0.001, \
            f"Sales account credit delta {delta_sales} != expected {expected_sale_taxable}"
        print(f"Sales account credit +{delta_sales:.2f} (expected {expected_sale_taxable})")

        # 4. CGST/SGST Output credit increased.
        after_cgst_out = _account_balance(session, cgst_out.id)[1]
        delta_cgst_out = after_cgst_out - before["cgst_out_cr"]
        assert abs(delta_cgst_out - float(expected_sale_cgst)) < 0.001, \
            f"CGST Output delta {delta_cgst_out} != expected {expected_sale_cgst}"
        print(f"CGST Output credit +{delta_cgst_out:.2f} (expected {expected_sale_cgst})")

        after_sgst_out = _account_balance(session, sgst_out.id)[1]
        delta_sgst_out = after_sgst_out - before["sgst_out_cr"]
        assert abs(delta_sgst_out - float(expected_sale_sgst)) < 0.001, \
            f"SGST Output delta {delta_sgst_out} != expected {expected_sale_sgst}"
        print(f"SGST Output credit +{delta_sgst_out:.2f} (expected {expected_sale_sgst})")

        # 5. Supplier ledger account credit increased by purchase total.
        after_supp_cr = _account_balance(session, supp_ledger.id)[1]
        delta_supp = after_supp_cr - before["supp_cr"]
        assert abs(delta_supp - float(expected_purch_total)) < 0.001, \
            f"Supplier ledger credit delta {delta_supp} != expected {expected_purch_total}"
        print(f"Supplier ledger credit +{delta_supp:.2f} (expected {expected_purch_total})")

        # 6. Purchase Account debit increased by taxable amount.
        after_purchase_dr = _account_balance(session, purchase_acct.id)[0]
        delta_purchase = after_purchase_dr - before["purchase_dr"]
        assert abs(delta_purchase - float(expected_purch_taxable)) < 0.001, \
            f"Purchase account debit delta {delta_purchase} != expected {expected_purch_taxable}"
        print(f"Purchase account debit +{delta_purchase:.2f} (expected {expected_purch_taxable})")

        # 7. CGST/SGST Input debit increased.
        after_cgst_in = _account_balance(session, cgst_in.id)[0]
        delta_cgst_in = after_cgst_in - before["cgst_in_dr"]
        assert abs(delta_cgst_in - float(expected_purch_cgst)) < 0.001, \
            f"CGST Input delta {delta_cgst_in} != expected {expected_purch_cgst}"
        print(f"CGST Input debit +{delta_cgst_in:.2f} (expected {expected_purch_cgst})")

        after_sgst_in = _account_balance(session, sgst_in.id)[0]
        delta_sgst_in = after_sgst_in - before["sgst_in_dr"]
        assert abs(delta_sgst_in - float(expected_purch_sgst)) < 0.001, \
            f"SGST Input delta {delta_sgst_in} != expected {expected_purch_sgst}"
        print(f"SGST Input debit +{delta_sgst_in:.2f} (expected {expected_purch_sgst})")

    finally:
        session.close()

    print("PASS")


if __name__ == "__main__":
    main()
