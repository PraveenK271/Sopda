# ROADMAP.md — Gemini ERP

The big picture, so you always know where you are and what comes next.
Build phases in order. Do not jump ahead — each phase relies on the one before it.

---

## ▶ Phase 1 — Core foundation  (CURRENT FOCUS)

The billing + inventory loop that everything else depends on.

- Item Master
- Customer Master (basic, for GST invoices)
- Sales Invoice with automatic stock deduction
- GST calculation (CGST/SGST/IGST)
- PDF invoice
- Sales log / basic reports

**Why first:** this is exactly what broke before (billing worked, inventory
didn't). Get it rock-solid and the rest becomes repetition of the same pattern.

Detailed steps: see `CHECKLIST.md`.

---

## Phase 2 — Purchases & full accounting

Once sales reduce stock correctly, do the mirror image: purchases that ADD stock.

- Supplier Master
- Purchase Order → Goods Receipt → Purchase Invoice (adds IN stock_transactions)
- Accounting engine (auto journal entries for each sale/purchase)
- Ledgers, Day Book, Trial Balance, Profit & Loss, Balance Sheet
- GST registers and returns (GSTR-1, GSTR-3B, HSN summary)
- Banking: receipts, payments, reconciliation

**Note:** purchases use the SAME `stock_transactions` table, just type 'IN'.
That is the payoff of getting the schema right in Phase 1.

---

## Phase 3 — Documents & AI

- OCR: scan supplier bills (PDF/JPG/PNG) and extract data for you to confirm
- Document storage
- AI reports in plain English ("show sales for April", "items below reorder level")
- Inventory forecasting and smart purchase suggestions

---

## Phase 4 — Going multi-user

- Switch the database from SQLite to Microsoft SQL Server
  (mostly a connection-string change because we used SQLAlchemy)
- Multi-user access and roles
- Remote access
- Mobile companion app

---

## How to use these three files

- **CLAUDE.md** — the rulebook Claude Code reads for context and conventions.
- **CHECKLIST.md** — your tick-list for the current phase; build one item at a time.
- **ROADMAP.md** — this file; the map so you never lose the thread.

Keep all three (plus `Instructions_Claude.txt`) inside the project folder.
