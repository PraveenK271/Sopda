# CLAUDE.md — Working Rules for Gemini ERP

This file is for Claude Code. Read it before doing any work in this project.
The full feature spec lives in `Instructions_Claude.txt`. This file is the
day-to-day rulebook. If the two ever disagree, follow this file for Phase 1.

---

## What we are building right now

A Windows desktop ERP for an Indian trading business.

**Phase 1 goal (current focus):** Item Master → Sales Invoice → stock auto-deducts
→ sale logged in the database. Nothing else yet. Do not start other modules until
this core loop works end to end.

A previous version could create invoices but could NOT track inventory, because
invoices were saved without ever reducing stock. Fixing that is the whole point
of Phase 1. See "The stock rule" below — it is the most important rule here.

---

## Tech stack

- Language: Python
- UI: PySide6 (Qt)
- Database access: SQLAlchemy (ORM)
- Database: **SQLite for now** (a single local file). We will switch to Microsoft
  SQL Server later for multi-user (Phase 4). Because we use SQLAlchemy, this switch
  is mostly a connection-string change, so write database-neutral code.
- PDF: ReportLab
- Excel export: OpenPyXL

---

## Folder structure (keep to this)

```
gemini_erp/
  models/        # SQLAlchemy table definitions ONLY
  services/      # ALL business logic lives here
  ui/            # PySide6 screens: collect input, show results, nothing more
  reports/       # PDF / Excel generation
  database.py    # DB connection + session setup
  main.py        # app entry point
```

---

## Golden rules (do not break these)

1. **No business logic in the UI.** UI screens only collect input and display
   output. Saving an invoice, reducing stock, calculating GST — all of that goes
   in a service class under `services/`. If a UI file starts doing calculations
   or writing to the database directly, that is a bug.

2. **The stock rule.** Never store "current stock" as a number that gets edited
   directly. Stock is calculated from a log of movements in the
   `stock_transactions` table:
   `current_stock = opening_stock + sum(IN quantities) − sum(OUT quantities)`

3. **One transaction = all or nothing.** When a sales invoice is saved, the
   invoice header, its line items, AND the matching OUT stock_transactions must
   all be written inside a SINGLE database transaction (one commit). If any part
   fails, the whole thing rolls back. This is what keeps billing and inventory
   permanently in sync.

4. **Build → test → confirm → next.** Do one milestone at a time (see
   `CHECKLIST.md`). After each one, run it and confirm it works before starting
   the next. Do not stack new code on untested code.

---

## Core tables (Phase 1)

1. **items** — id, code, name, hsn_code, gst_rate, unit, opening_stock, reorder_level
2. **customers** — id, name, gstin, address, state
3. **sales_invoices** — id, invoice_no, date, customer_id, taxable_amount,
   cgst, sgst, igst, total
4. **sales_invoice_items** — id, invoice_id, item_id, quantity, rate, amount, gst_amount
5. **stock_transactions** — id, item_id, type ('IN'/'OUT'), quantity,
   reference_type ('SALE'), reference_id, date

Add these audit columns to every table (from the spec):
`created_date, created_by, modified_date, modified_by, is_deleted`.
Use `is_deleted` for soft deletes — never physically delete rows.

---

## GST logic (simple version for Phase 1)

The business is in Andhra Pradesh.

- If the customer's state == our state → split the GST rate into **CGST + SGST**
  (half each). Example: 18% rate → 9% CGST + 9% SGST.
- If the customer is in a different state → use **IGST** (the full rate).

Keep this in a service so it can be reused everywhere.

---

## Coding standards

- Keep business logic in service classes (Service Layer pattern).
- Use clear names — no codes-only naming.
- Add logging and exception handling around database operations.
- Write a small test/check after each milestone to prove it works.
- Comment the "why," not the obvious "what."
