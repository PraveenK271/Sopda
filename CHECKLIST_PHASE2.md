# CHECKLIST_PHASE2.md — Phase 2 Part 1: Purchases (mirrors Phase 1)

Phase 2 (per ROADMAP.md) is large: Supplier Master, Purchases, Accounting
engine, Ledgers/Trial Balance/P&L/Balance Sheet, GST returns, Banking.
That is too much to plan as one milestone list, so we start with the part
that mirrors Phase 1 directly: purchases that ADD stock via the SAME
`stock_transactions` table (type 'IN'). Accounting/GST-returns/Banking will
get their own checklist once this part is built, tested and confirmed.

Work top to bottom, same rule as CHECKLIST.md: **run and confirm each item
before starting the next.**

---

## Milestone 6 — Supplier Master

- [x] Create `models/supplier.py` (`Supplier`, mirrors `Customer`: name,
      gstin, address, state + audit columns)
- [x] Register `Supplier` in `models/__init__.py`
- [x] Create `services/supplier_service.py` (`SupplierService`:
      `add_supplier()`, `list_suppliers()`, mirrors `CustomerService`)
- [x] **Test it:** a script adds a supplier and lists it back correctly

---

## Milestone 7 — Purchase Invoice core loop (most important)

- [x] Create `models/purchase_invoice.py` (`PurchaseInvoice`: invoice_no,
      date, supplier_id, taxable_amount, cgst, sgst, igst, total + audit)
- [x] Create `models/purchase_invoice_item.py` (`PurchaseInvoiceItem`:
      invoice_id, item_id, quantity, rate, amount, gst_amount + audit)
- [x] Register both in `models/__init__.py`
- [x] Create `services/purchase_service.py` —
      `PurchaseService.create_purchase_invoice()` that, in ONE database
      transaction: saves the invoice header, saves each line item, and
      writes one IN `stock_transaction` per line
      (reference_type='PURCHASE')
- [x] Reuse `gst_service.split_gst()` with the supplier's state (same logic:
      same state -> CGST+SGST, different state -> IGST, now representing
      input tax credit instead of output tax)
- [x] **Test it first with a script, not the UI:** record a purchase of 10
      units of an item -> current stock goes UP by 10, and the invoice +
      lines + stock rows all exist

---

## Milestone 8 — Purchase entry UI

- [x] Build `ui/purchase.py` (`PurchaseScreen`, mirrors `BillingScreen`):
      header (supplier invoice no/date/supplier), inline "New Supplier" box,
      item/qty/rate line entry, live GST totals, "Save Purchase" button
- [x] Add a "Purchases" tab in `main.py`
- [x] **Test it end to end:** record a real purchase from the screen ->
      stock goes up correctly and the purchase is in the database
      (verified with a temporary headless PySide6 test, then removed -
      same approach as the Milestone 4 PDF button check)

---

## Milestone 9 — Purchase log

- [x] Add `PurchaseService.list_purchase_invoices()` and
      `get_purchase_invoice_details(invoice_id)` (mirrors
      `SalesService.list_invoices` / `get_invoice_details`)
- [x] Build `ui/purchase_log.py` (`PurchaseLogScreen` + detail dialog,
      mirrors `ui/sales_log.py`)
- [x] Add a "Purchase Log" tab in `main.py`
- [x] **Test it:** every purchase you create shows up in the list

---

## Phase 2 Part 1 is DONE when:

You can add a supplier, record a purchase, watch stock go UP, and see the
purchase logged — the mirror image of Phase 1. After this, ask the user
before planning the next chunk (Accounting engine / Ledgers / GST returns /
Banking), since that is a much larger body of work.

**STATUS: DONE (Milestones 6-9 all complete and tested).** Ask the user
before starting Accounting / Ledgers / GST returns / Banking - see
`ROADMAP.md` Phase 2 for the remaining scope.
