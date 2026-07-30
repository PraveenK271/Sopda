"""Check: PurchaseService.update_purchase_invoice() reverses the original
stock-IN and journal entry and re-applies the edited ones, all-or-nothing.

Editing a 10-qty purchase down to 4 must leave net stock +4 (not +14), exactly
one active stock movement / line / journal entry, and a still-balanced ledger.

Run with: python check_purchase_edit.py
"""

import time
from datetime import date

from sqlalchemy import false, true
from database import get_session
from models import JournalEntry, PurchaseInvoice, PurchaseInvoiceItem, StockTransaction
from services.accounting_service import AccountingService
from services.item_service import ItemService
from services.purchase_service import PurchaseService
from services.supplier_service import SupplierService


def _get_or_create_item(svc, code, name, gst_rate):
    for it in svc.list_items():
        if it["code"] == code:
            return it["id"]
    return svc.add_item(code=code, name=name, gst_rate=gst_rate, opening_stock=0).id


def _get_or_create_supplier(svc, name, state, gstin):
    for s in svc.list_suppliers():
        if s["name"] == name:
            return s["id"]
    return svc.add_supplier(name=name, gstin=gstin, state=state, address="Test").id


def _active(session, model, invoice_id):
    return (
        session.query(model)
        .filter(
            model.reference_type == "PURCHASE",
            model.reference_id == invoice_id,
            model.is_deleted == false(),
        )
        .all()
    )


def _tb_balances():
    tb = AccountingService.get_trial_balance()
    return round(sum(r["debit"] for r in tb), 2) == round(sum(r["credit"] for r in tb), 2)


def main():
    item_svc, supp_svc, purch = ItemService(), SupplierService(), PurchaseService()

    item_id = _get_or_create_item(item_svc, "CHK-PE-ITEM", "PurchEdit Item", 18)
    supplier_id = _get_or_create_supplier(
        supp_svc, "CHK-PE Supplier", "Andhra Pradesh", "37AAAAA0000A1Z5"
    )

    stock_before = item_svc.get_current_stock(item_id)
    inv_no = f"CHK-PE-{int(time.time())}"

    invoice = purch.create_purchase_invoice(
        invoice_no=inv_no, invoice_date=date.today(), supplier_id=supplier_id,
        lines=[{"item_id": item_id, "quantity": 10, "rate": 100}],
    )
    invoice_id = invoice.id
    assert item_svc.get_current_stock(item_id) == stock_before + 10
    assert _tb_balances(), "trial balance should balance after create"
    print(f"[setup] created {inv_no}: stock {stock_before}->{stock_before + 10}, total={invoice.total}")

    # --- EDIT: qty 10 -> 4 (same item/rate) ---
    purch.update_purchase_invoice(
        invoice_id, invoice_no=inv_no, invoice_date=date.today(), supplier_id=supplier_id,
        lines=[{"item_id": item_id, "quantity": 4, "rate": 100}],
    )

    # [1] net stock effect is +4, proving the original +10 IN was reversed.
    stock_after = item_svc.get_current_stock(item_id)
    assert stock_after == stock_before + 4, (stock_after, stock_before)
    print(f"[1] stock after edit = {stock_after} (baseline {stock_before} +4) OK")

    session = get_session()
    try:
        txns = _active(session, StockTransaction, invoice_id)
        assert len(txns) == 1 and float(txns[0].quantity) == 4, txns
        entries = _active(session, JournalEntry, invoice_id)
        assert len(entries) == 1, entries
        jls = [l for l in entries[0].lines if not l.is_deleted]
        dr = round(sum(float(l.debit) for l in jls), 2)
        cr = round(sum(float(l.credit) for l in jls), 2)
        assert dr == cr, (dr, cr)

        lines = (
            session.query(PurchaseInvoiceItem)
            .filter(
                PurchaseInvoiceItem.invoice_id == invoice_id,
                PurchaseInvoiceItem.is_deleted == false(),
            )
            .all()
        )
        assert len(lines) == 1 and float(lines[0].quantity) == 4

        inv = session.get(PurchaseInvoice, invoice_id)
        assert float(inv.taxable_amount) == 400.0, inv.taxable_amount
        assert round(float(inv.total), 2) == 472.0, inv.total  # 400 + 18%
        print("[2] exactly 1 active stock txn / journal / line; journal balances; "
              "header taxable=400 total=472 OK")
    finally:
        session.close()

    assert _tb_balances(), "trial balance should still balance after edit"
    print("[3] trial balance still balances after edit OK")

    details = purch.get_purchase_invoice_details(invoice_id)
    assert len(details["lines"]) == 1 and details["lines"][0]["quantity"] == 4.0
    print("[4] get_purchase_invoice_details shows only the 1 edited line OK")

    print("\nAll purchase-edit checks passed.")


if __name__ == "__main__":
    main()
