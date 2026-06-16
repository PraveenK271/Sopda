"""Milestone 18 check: GST Sales/Purchase registers + HSN summary.

Self-contained fixtures on a sentinel date (FY 2019-20) so the date-filtered
reports see ONLY these rows and nothing from the real dev DB / other checks:

  Items
    CHK-M18-ITEM-A : HSN 1001, 18% GST
    CHK-M18-ITEM-B : HSN 2002, 5%  GST
  Customers
    CHK-M18-CUST-GST   : AP, has GSTIN   -> B2B, intra-state (CGST+SGST)
    CHK-M18-CUST-NOGST : AP, no GSTIN    -> B2C, intra-state
    CHK-M18-CUST-KA    : Karnataka, GSTIN-> B2B, inter-state (IGST)
  Supplier
    CHK-M18-SUPP : AP, has GSTIN

  Sales (date 2019-04-15)
    -> CUST-GST   : item A 10x100 = 1000 taxable, 18% -> CGST 90 SGST 90, tot 1180
    -> CUST-NOGST : item B  4x50  =  200 taxable,  5% -> CGST  5 SGST  5, tot  210
    -> CUST-KA    : item A  5x100 =  500 taxable, 18% -> IGST 90,        tot  590
  Purchase (date 2019-04-15)
    -> SUPP       : item A 20x50  = 1000 taxable, 18% -> CGST 90 SGST 90, tot 1180

build_fixtures() is reused by check_milestone19.py.

Run with: ../venv/Scripts/python.exe check_milestone18.py
"""

from datetime import date
from decimal import Decimal

from database import get_session
from models import (
    JournalEntry,
    JournalEntryLine,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    SalesInvoice,
    SalesInvoiceItem,
    StockTransaction,
)
from services.customer_service import CustomerService
from services.gst_report_service import GstReportService
from services.item_service import ItemService
from services.purchase_service import PurchaseService
from services.sales_service import SalesService
from services.supplier_service import SupplierService

FIXTURE_DATE = date(2019, 4, 15)
DATE_FROM = date(2019, 4, 1)
DATE_TO = date(2019, 4, 30)

ITEM_A = "CHK-M18-ITEM-A"
ITEM_B = "CHK-M18-ITEM-B"
CUST_GST = "CHK-M18-CUST-GST"
CUST_NOGST = "CHK-M18-CUST-NOGST"
CUST_KA = "CHK-M18-CUST-KA"
SUPP = "CHK-M18-SUPP"

SALE_GST_NO = "CHK-M18-SALE-GST"
SALE_NOGST_NO = "CHK-M18-SALE-NOGST"
SALE_KA_NO = "CHK-M18-SALE-KA"
PURCH_NO = "CHK-M18-PURCH"


def _get_or_create_customer(svc, name, gstin, state):
    for c in svc.list_customers():
        if c["name"] == name:
            return c
    obj = svc.add_customer(name=name, gstin=gstin, address="Test", state=state)
    return {"id": obj.id, "name": obj.name}


def _get_or_create_supplier(svc, name, gstin, state):
    for s in svc.list_suppliers():
        if s["name"] == name:
            return s
    obj = svc.add_supplier(name=name, gstin=gstin, address="Test", state=state)
    return {"id": obj.id, "name": obj.name}


def _get_or_create_item(svc, code, hsn, rate):
    for i in svc.list_items():
        if i["code"] == code:
            return i
    obj = svc.add_item(code=code, name=code, hsn_code=hsn, gst_rate=rate,
                       unit="PCS", opening_stock=1000, reorder_level=0)
    return {"id": obj.id}


def _delete_journal_for(session, reference_type, reference_id):
    je = (
        session.query(JournalEntry)
        .filter(JournalEntry.reference_type == reference_type,
                JournalEntry.reference_id == reference_id)
        .first()
    )
    if je:
        session.query(JournalEntryLine).filter(JournalEntryLine.entry_id == je.id).delete()
        session.delete(je)


def _delete_sale(session, invoice_no):
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


def _delete_purchase(session, invoice_no):
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


def build_fixtures():
    """Create (idempotently) the M18 customers/items/supplier and rebuild the
    four invoices on the sentinel date. Returns the (date_from, date_to) range."""
    custs = CustomerService()
    item_svc = ItemService()
    cust_gst = _get_or_create_customer(custs, CUST_GST, "37AAAAA0000A1Z5", "Andhra Pradesh")
    cust_nogst = _get_or_create_customer(custs, CUST_NOGST, None, "Andhra Pradesh")
    cust_ka = _get_or_create_customer(custs, CUST_KA, "29BBBBB0000B1Z5", "Karnataka")
    supp = _get_or_create_supplier(SupplierService(), SUPP, "37EEEEE0000E1Z5", "Andhra Pradesh")
    item_a = _get_or_create_item(item_svc, ITEM_A, "1001", 18)
    item_b = _get_or_create_item(item_svc, ITEM_B, "2002", 5)

    session = get_session()
    try:
        for no in (SALE_GST_NO, SALE_NOGST_NO, SALE_KA_NO):
            _delete_sale(session, no)
        _delete_purchase(session, PURCH_NO)
    finally:
        session.close()

    SalesService().create_invoice(
        invoice_no=SALE_GST_NO, invoice_date=FIXTURE_DATE, customer_id=cust_gst["id"],
        lines=[{"item_id": item_a["id"], "quantity": Decimal("10"), "rate": Decimal("100")}],
    )
    SalesService().create_invoice(
        invoice_no=SALE_NOGST_NO, invoice_date=FIXTURE_DATE, customer_id=cust_nogst["id"],
        lines=[{"item_id": item_b["id"], "quantity": Decimal("4"), "rate": Decimal("50")}],
    )
    SalesService().create_invoice(
        invoice_no=SALE_KA_NO, invoice_date=FIXTURE_DATE, customer_id=cust_ka["id"],
        lines=[{"item_id": item_a["id"], "quantity": Decimal("5"), "rate": Decimal("100")}],
    )
    PurchaseService().create_purchase_invoice(
        invoice_no=PURCH_NO, invoice_date=FIXTURE_DATE, supplier_id=supp["id"],
        lines=[{"item_id": item_a["id"], "quantity": Decimal("20"), "rate": Decimal("50")}],
    )
    return DATE_FROM, DATE_TO


def _find(rows, invoice_no):
    return next(r for r in rows if r["invoice_no"] == invoice_no)


def main():
    date_from, date_to = build_fixtures()

    # --- Sales register ---
    sales = GstReportService.get_sales_register(date_from, date_to)
    assert len(sales) == 3, f"Expected 3 sales register rows, got {len(sales)}"

    r = _find(sales, SALE_GST_NO)
    assert (r["taxable_amount"], r["cgst"], r["sgst"], r["igst"], r["total"]) == (1000.0, 90.0, 90.0, 0.0, 1180.0), r
    assert r["customer_gstin"] == "37AAAAA0000A1Z5" and r["hsn_code"] == "1001", r

    r = _find(sales, SALE_NOGST_NO)
    assert (r["taxable_amount"], r["cgst"], r["sgst"], r["igst"], r["total"]) == (200.0, 5.0, 5.0, 0.0, 210.0), r
    assert not r["customer_gstin"], r

    r = _find(sales, SALE_KA_NO)
    assert (r["taxable_amount"], r["cgst"], r["sgst"], r["igst"], r["total"]) == (500.0, 0.0, 0.0, 90.0, 590.0), r
    print("Sales register: 3 rows OK (intra CGST/SGST, B2C, inter-state IGST)")

    # --- Purchase register ---
    purch = GstReportService.get_purchase_register(date_from, date_to)
    assert len(purch) == 1, f"Expected 1 purchase register row, got {len(purch)}"
    p = purch[0]
    assert (p["taxable_amount"], p["cgst"], p["sgst"], p["igst"], p["total"]) == (1000.0, 90.0, 90.0, 0.0, 1180.0), p
    assert p["supplier_name"] == SUPP and p["hsn_code"] == "1001", p
    print("Purchase register: 1 row OK")

    # --- HSN summary (SALES) ---
    hsn = GstReportService.get_hsn_summary(date_from, date_to, "SALES")
    by_key = {(h["hsn_code"], h["gst_rate"]): h for h in hsn}
    assert len(hsn) == 2, f"Expected 2 HSN groups, got {len(hsn)}: {hsn}"

    a = by_key[("1001", 18.0)]
    assert (a["quantity"], a["taxable_amount"], a["cgst"], a["sgst"], a["igst"], a["total"]) == \
        (15.0, 1500.0, 90.0, 90.0, 90.0, 1770.0), a

    b = by_key[("2002", 5.0)]
    assert (b["quantity"], b["taxable_amount"], b["cgst"], b["sgst"], b["igst"], b["total"]) == \
        (4.0, 200.0, 5.0, 5.0, 0.0, 210.0), b
    print("HSN summary (SALES): 2 groups OK (HSN 1001@18%, HSN 2002@5%)")

    # --- HSN summary (PURCHASE) ---
    hsn_p = GstReportService.get_hsn_summary(date_from, date_to, "PURCHASE")
    assert len(hsn_p) == 1 and hsn_p[0]["hsn_code"] == "1001", hsn_p
    assert hsn_p[0]["taxable_amount"] == 1000.0 and hsn_p[0]["quantity"] == 20.0, hsn_p[0]
    print("HSN summary (PURCHASE): 1 group OK")

    print("PASS")


if __name__ == "__main__":
    main()
