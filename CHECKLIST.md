# CHECKLIST.md — Phase 1 Build Order

Work top to bottom. **Run and confirm each item before starting the next.**
Tick the box `[x]` when it works. The "Test it" line is how you know it's done.

---

## Milestone 0 — Project setup

- [x] Create a virtual environment (`python -m venv venv`) and activate it
- [x] Install packages: `pip install PySide6 SQLAlchemy reportlab openpyxl`
- [x] Create the folder structure (models, services, ui, reports)
- [x] Create `database.py` (SQLite connection + session setup)
- [x] Create `main.py` that opens one empty PySide6 window
- [x] **Test it:** run `python main.py` — a blank window appears and closes cleanly

---

## Milestone 1 — Database foundation

- [x] Create SQLAlchemy models for all 5 core tables (items, customers,
      sales_invoices, sales_invoice_items, stock_transactions)
- [x] Add the audit columns to every table (created_date, created_by,
      modified_date, modified_by, is_deleted)
- [x] Run a one-time script that creates the database file and all tables
- [x] **Test it:** open the SQLite file (VS Code SQLite extension or DB Browser
      for SQLite) and confirm all 5 tables exist with the right columns

---

## Milestone 2 — Item Master

- [x] Create `ItemService` with: add_item(), list_items(), get_current_stock(item_id)
- [x] `get_current_stock` must CALCULATE stock from stock_transactions
      (opening_stock + sum IN − sum OUT), not read a stored number
- [x] Create a simple UI screen to add an item and view the item list with stock
- [x] **Test it:** add an item with opening stock 100 → the list shows it with
      current stock = 100

---

## Milestone 3 — The core sale loop (most important)

- [x] Create `SalesService.create_invoice()` that, in ONE database transaction:
      saves the invoice header, saves each line item, and writes one OUT
      stock_transaction per line
- [x] Add the GST split logic (CGST+SGST same state, IGST otherwise)
- [x] **Test it first with a script, not the UI:** sell 10 of the item from
      Milestone 2 → re-check current stock = 90, and the invoice + lines + stock
      rows all exist
- [x] Now build the billing UI screen: pick items, enter quantity, see totals,
      save the invoice
- [x] **Test it end to end:** create a real invoice from the screen → stock drops
      correctly and the sale is in the database

---

## Milestone 4 — PDF invoice

- [x] Create a function in `reports/` that turns a saved invoice into a PDF
      (ReportLab): seller details, customer, items, GST breakup, total
- [x] Add a "Print / Save PDF" button on the billing screen
- [x] **Test it:** save an invoice → a correct PDF is generated

---

## Milestone 5 — Sales log / basic report

- [x] Add a screen listing past invoices (date, invoice no, customer, total)
- [x] Allow opening one invoice to view its details
- [x] **Test it:** every invoice you created shows up in the list

---

## Phase 1 is DONE when:

You can add an item, bill it, watch stock go down, see the sale logged, and print
a PDF — all without anything going out of sync. That is the foundation the rest of
the ERP is built on.
