# CHECKLIST_HISTORICAL_IMPORT.md — Bringing the Books In

PLANNING DOCUMENT — nothing here has been built yet.

Goal: get this financial year's real trading history out of the manual bill
books and into Gemini ERP, so that stock levels, customer/supplier balances
and the books all reflect reality.

This is a **separate track** from Phase 4. It does not depend on multi-user
or the mobile app, and Phase 4 does not depend on it. Milestones are numbered
H1-H6 to keep them out of the Phase 4 sequence.

Same rule as every other checklist (`CLAUDE.md` applies):
**build -> test -> confirm -> next, one milestone at a time.**

> **Ordering note:** the generic import engine (H1) is built *before* opening
> balances (H2), even though opening balances are entered first when you
> actually use the system. Reason: the engine is the shared tool everything
> else uses. Build and test the tool once, then use it five times.

---

## Decisions already made (do not re-litigate without asking)

1. **Cut-off date is 1 April 2026.** Everything on or after that date is
   entered as individual transactions. Everything before it is collapsed
   into opening balances. FY 2026-27 only — earlier years are not entered.

2. **Target database is the clean SQL Server `GeminiERP` database**
   (`HP\GEMINI`), NOT the SQLite dev file. `gemini_erp.db` contains test
   fixtures (`DA001`, `CHK-M3-*`, `CHK-M7-*`, `CHK-M11-*` etc.) which would
   pollute real reports permanently. Real history goes into the clean MSSQL
   database; the SQLite file stays as a disposable dev sandbox.

3. **Excel layout: one row per line item, header columns repeated.**
   Import groups rows by invoice number. Chosen over separate header/line
   sheets because fill-down makes it much faster to type from a bill book.

4. **Two-stage import: validate, then import.** Validation reads the whole
   file and writes NOTHING to the database. The user sees a report of every
   problem before deciding to proceed. No exceptions to this.

5. **Reuse the existing services.** A backdated invoice is just an invoice
   with an old date — same `SalesService.create_invoice()`, same single
   transaction, same stock movement, same journal entry. Do NOT build a
   parallel save path for imports. Only the *screen* is new.

6. **Items must already exist; customers/suppliers can be auto-created.**
   A sales sheet cannot supply HSN code, GST rate or unit, so an unknown
   item code is an ERROR. An unknown party name is a WARNING listed in the
   validation report, created only after the user confirms.

7. **Invoice numbers come from the physical bill book.** They are the legal
   record under GST. The system does not generate numbers for imported
   invoices.

8. **Opening stock is entered as QUANTITY only.** Putting a rupee value on
   opening stock needs item costing, which does not exist (see Phase 2 Part 2
   Decision 3 — no Trading Account / COGS yet). Quantity fixes inventory,
   which is the point. The balance-sheet value figure is a separate
   conversation with the accountant.

---

## New tables (2) and services (2), at a glance

| Table / Service | Milestone | Purpose |
|---|---|---|
| `import_logs` | H1 | One row per import run — file, type, counts, status, who |
| `period_locks` | H6 | Locks a date range so imported history cannot be edited |
| `services/import_service.py` | H1 | Generic read -> validate -> report -> import engine |
| `services/opening_balance_service.py` | H2 | Opening stock + party balances + opening journal |

New UI: `ui/data_import.py` (one screen, a sub-tab per import type),
`ui/opening_balances.py`, `ui/verify_and_lock.py`.

Uses OpenPyXL, already a project dependency.

---

## Order you will actually USE this (not the build order)

1. Item Master and (optionally) Customer/Supplier masters in place
2. **Opening balances as of 31 March 2026** (H2)
3. **Purchases** from 1 Apr 2026 (H4) — adds stock
4. **Sales** from 1 Apr 2026 (H3) — removes stock
5. **Receipts and payments** (H5)
6. **Verify against a physical count, then lock** (H6)

Purchases before sales so stock does not dip negative mid-import.

---

## Milestone H1 — Import engine + template generator (foundation)  ✅ DONE (2026-07-31)

- [x] `models/import_log.py` — `ImportLog` (file_name, import_type, run_date,
      rows_read, records_created, status, notes + audit; explicit String
      lengths). Registered in `models/__init__` + `create_db`; `import_logs`
      table created on SQL Server.

- [x] `services/import_service.py` — `ImportService` generic engine:
      `read_sheet()` (header match order-independent/case-insensitive; missing/
      misspelled column is a hard error naming it; blank + EXAMPLE rows skipped),
      `validate()` (writes NOTHING) -> `ValidationReport` (errors/warnings as
      `{row_number, message}`, `is_importable`, `summary`). Column definitions
      for ALL six types live in `IMPORT_DEFS` (a `ColumnSpec` list per type with
      roles). Shared validators: date `DD-MM-YYYY` on/after 01-04-2026
      (unparseable = ERROR, never guessed); numbers parse, quantity>0, rate/
      total/opening_qty>=0, amount>0; `item_code` exists & not deleted; party
      name resolves else WARNING; SALES `invoice_no` not already in DB (ERROR).
      Per-supplier `bill_no` (PURCHASES) + total cross-check are wired in H3/H4.

- [x] `generate_template(import_type, save_path)` — bold frozen header; date
      columns pre-formatted as Text (`@`); one yellow example row; a NOTE column
      carrying the `EXAMPLE - DELETE ME` marker (so the reader always skips it,
      keeping every data column's example realistic); an `Instructions` sheet
      describing every column.

- [x] `ui/data_import.py` — Data Import screen, one sub-tab per type: Download
      Template, file picker, Validate (report table, errors red / warnings
      amber, summary line), and an Import button that stays **disabled** until a
      zero-error validation on that exact file (editing the path re-disables it).
      Per-type import lands in H2-H5 (dispatch raises a clear "added in a later
      milestone" until then).

- [x] Added "Data Import" as a top-level tab, **Administrator only** — new
      `MODULE_DATA_IMPORT` permission (in `ALL_MODULES`, so only the
      all-permissions Administrator gets it). NOTE: `ensure_roles_and_admin`
      now **reconciles** existing roles' permissions to `permissions.py` on
      startup, so adding a module key takes effect on upgrade without a DB edit.

- [x] **Tested — `check_h1.py` PASS on SQL Server AND SQLite:** template headers
      round-trip through `read_sheet` (example row skipped); a misspelled header
      is rejected naming `invoice_no`; a file with a bad date + zero quantity +
      unknown item code yields EXACTLY 3 errors on rows 3/4/5; and validation
      wrote nothing (sales_invoices/stock_transactions/journal_entries counts
      unchanged). Tab RBAC confirmed offscreen (Admin sees it, Sales User does
      not); RBAC regressions (M26/M27/M29) still PASS.

---

## Milestone H2 — Opening balances (as of 31 March 2026)  ✅ DONE (2026-07-31)

> **The single biggest risk in this whole track.** `opening_stock` must be
> the stock on the CUT-OFF DATE, not today's physical count.
> Correct: 60 on 31 Mar + 80 bought − 40 sold = 100 today.
> Wrong: 100 (today's count) + 80 − 40 = 140.
> This warning is shown ON the Opening Balances screen (red), per requirement.

**Double-count trap found & handled:** every balance report already computes
`opening_balance` FIELD + journal-line totals. Setting the field AND posting a
journal to the same ledger would double-count (outstanding 100k not 50k). So the
`set_*` methods STAGE the balances on the `opening_balance` fields, and
`post_opening_journal()` converts them into the journal and then ZEROES those
fields — every balance is counted exactly once (via the journal). Verified by
check_h2 (outstanding = 50,000, not 100,000).

- [x] `services/opening_balance_service.py` — `OpeningBalanceService`:
      `set_opening_stock` (sets `items.opening_stock`, NO stock_transaction),
      `set_party_opening_balance` (stages on the party ledger), `set_cash_bank_opening`,
      `post_opening_journal(session, as_of_date, created_by)` — reads the staged
      balances, posts ONE balanced entry (`reference_type='OPENING'`, Dr/Cr per
      staged type + `OPENING_EQUITY` balancing) via
      `AccountingService.post_journal_entry()`, then clears the staged fields.
      Guard: refuses to run twice (raises if an OPENING journal exists).
      `OPENING_EQUITY` added to `chart_of_accounts` (EQUITY) + seeded; seeded on
      SQL Server.
- [x] Excel templates (via H1): `OPENING_STOCK` (item_code, opening_qty),
      `OPENING_BALANCES` (party_type, party_name, amount, balance_type).
      `ImportService.import_opening_stock` / `import_opening_balances` +
      dispatch; OPENING_BALANCES validation requires the party to already exist
      (ERROR). Import stages balances only — the journal is posted separately.
- [x] `ui/opening_balances.py` — three sections (Opening Stock / Party Balances /
      Cash-Bank), each with manual entry (+ Excel import for stock & party); the
      cut-off date + double-count warning in red at the top; a "Post Opening
      Journal" button disabled until staged balances exist. New Administrator-only
      tab (reuses `MODULE_DATA_IMPORT`).
- [x] **Tested — `check_h2.py` PASS (fresh SQLite; refuses to run on SQL Server
      as it posts a global journal):** opening stock 60 -> get_current_stock 60,
      0 stock_transactions; customer Dr 50k + supplier Cr 30k -> balanced OPENING
      entry, Trial Balance balances; customer outstanding 50,000 (single-counted);
      second post raises. Import path + tab RBAC verified offscreen. `OPENING_EQUITY`
      seeds clean on SQL Server; RBAC (M27/M29) + H1 regressions PASS.

---

## Milestone H3 — Sales import

Template `SALES` columns:

| Column | Notes |
|---|---|
| `invoice_no` | from the bill book; must be unique |
| `invoice_date` | `DD-MM-YYYY`, on/after 01-04-2026 |
| `customer_name` | auto-created after confirmation if unknown |
| `customer_gstin` | blank for B2C |
| `customer_state` | blank -> defaults to Andhra Pradesh (existing B2C rule) |
| `item_code` | must already exist |
| `quantity` | > 0 |
| `rate` | per unit, excluding GST |
| `invoice_total` | **cross-check**; the figure from the bill book, repeated on every row of the same invoice |

- [x] `ImportService.import_sales(file_path, created_by) -> ImportLog` DONE:
  - Groups rows by `invoice_no` (sheet order preserved).
  - **Total cross-check** and the same-date / same-customer checks live in
    VALIDATION (`_validate_sales_groups`) so the two-stage contract holds — a
    mismatch beyond ₹1 is an ERROR naming the invoice + computed + sheet total;
    two dates or two customers for one invoice_no is an ERROR. The computed
    total mirrors `create_invoice` exactly (amount quantized then `split_gst`)
    using the customer's effective state (existing customer's state, else the
    sheet's / AP default) so it never false-fails.
  - Calls the existing `SalesService.create_invoice()` per invoice (backdated
    date + book's invoice_no); GST split, stock OUT rows and the journal come
    free. Unknown customers are auto-created on import (the Import click is the
    confirmation — Decision 6).
  - Each invoice is its own transaction; on failure the run STOPS naming that
    invoice, earlier invoices stay saved, and a FAILED `ImportLog` records how
    far it got. Success writes an IMPORTED `ImportLog`.
- [x] **Negative stock during import:** no bypass flag needed — M28's oversell
      policy is already "allow but warn", so `create_invoice` records the sale
      regardless and returns `invoice.stock_warnings`; import_sales collects
      those into the `ImportLog` notes for H6 review.
- [x] **Tested — `check_h3.py` PASS (fresh SQLite; refuses on SQL Server):**
      3-invoice / 7-line file imports, stock A 100→82 & B 100→92, every invoice
      has a balanced journal; AP invoice CGST+SGST and Karnataka invoice IGST;
      a wrong `invoice_total` fails validation naming the invoice and writes
      nothing; a sale beyond stock is allowed (2−5=−3) and recorded in the
      ImportLog notes; re-running the file fails on duplicate `invoice_no`.
      check_h1 still PASS on SQL Server (SALES validation coexists).

---

## Milestone H4 — Purchase import

Template `PURCHASES` columns: `bill_no`, `bill_date`, `supplier_name`,
`supplier_gstin`, `supplier_state`, `item_code`, `quantity`, `rate`,
`bill_total`.

- [ ] `ImportService.import_purchases(file_path, created_by) -> ImportLog` —
      mirror of H3, calling the existing
      `PurchaseService.create_purchase_invoice()`. Stock IN rows and the
      `Dr Purchase / Dr Input GST / Cr Supplier` journal come free.
- [ ] `bill_no` uniqueness is **per supplier**, not global — two suppliers
      can legitimately both have a bill numbered `001`.
- [ ] Reminder for the user, not code: the Phase 3 OCR screen can scan
      purchase bills instead of typing them. Excel is better for bulk;
      OCR is better for the awkward ones. Both end up in the same service.
- [ ] **Test it:** `check_h4.py` — a 2-bill file imports, stock rises by the
      right amount, supplier outstanding increases by the bill totals, and
      the same `bill_no` under two different suppliers is accepted.

---

## Milestone H5 — Receipts & payments import

Template `RECEIPTS`: `date`, `customer_name`, `amount`, `mode`
(`CASH`/`BANK`), `bank_account_name` (required when mode is `BANK`),
`reference_no`.
Template `PAYMENTS`: same with `supplier_name`.

- [ ] `ImportService.import_receipts(...)` / `import_payments(...)` calling
      the existing `BankingService.record_receipt()` / `record_payment()`.
- [ ] Bank accounts must already exist (Milestone 16) — an unknown
      `bank_account_name` is an ERROR.
- [ ] Warn (do not block) if a receipt makes a customer's balance go
      credit — usually a sign of a missing invoice or a double-entered
      receipt, worth a look in H6.
- [ ] **Test it:** `check_h5.py` — import receipts covering the H3 invoices
      in full; those customers' outstanding drops to zero and the Cash/Bank
      ledger rises by the total received.

---

## Milestone H6 — Verify, then lock

This is the milestone that proves the whole exercise worked.

- [ ] `ui/verify_and_lock.py` — a reconciliation screen showing, side by
      side and with a difference column:
  - **Stock:** system current stock per item vs a `physical_qty` column the
    user types in (or imports). Highlight every non-zero difference.
  - **Customer outstanding:** system vs a figure typed from the book
  - **Supplier outstanding:** system vs the book
  - **Cash / bank balance:** system vs actual
  - Any item flagged as having gone negative during import (from the
    `ImportLog` notes)
- [ ] `models/period_lock.py` — `PeriodLock`: `id`, `locked_upto_date`,
      `locked_by`, `locked_date`, `reason` + audit.
- [ ] Enforce the lock in the services (NOT the UI): `SalesService`,
      `PurchaseService` and `BankingService` must refuse to create or modify
      any record dated on or before `locked_upto_date`, raising a clear
      error. Putting this in the UI only would leave the import path and any
      future API able to bypass it.
- [ ] Administrator-only "Unlock" with a typed reason, recorded in the
      lock row. Locks should be annoying to undo, not impossible.
- [ ] **Test it:** `check_h6.py`
      - with a lock at 31-07-2026, creating an invoice dated 15-07-2026
        raises; one dated 05-08-2026 saves normally
      - the verification screen's stock figures match
        `ItemService.get_current_stock()` for every item

---

## This track is DONE when:

You do a physical stock count and it matches what the system shows. Customer
outstanding matches your book. Supplier outstanding matches your book. Cash
and bank match. The period is locked, and from 1 August 2026 onward every
sale and purchase is entered in the software as it happens — no more bill
book.

That single matching stock count is the proof. Everything else is detail.

---

## Before you start entering real data

- [ ] Finish Milestones 26/27 (login) first, so every imported record
      carries a real `created_by` instead of `None`
- [ ] **Back up the `GeminiERP` database** (SSMS -> right-click the database
      -> Tasks -> Back Up). Do this before H2 and again before each bulk
      import. A bad bulk import is far harder to unpick than a bad single
      entry.
- [ ] Do a dry run: type 5 real invoices into the sales template, import
      them, check the numbers by hand. Fix whatever surprises you *before*
      typing four months of data.

---

## Deliberately NOT in this track

- Importing FY 2025-26 or earlier (cut-off decision)
- Opening stock *valuation* in rupees (needs item costing / COGS)
- Editing or reversing an imported invoice in bulk (delete and re-import
  a corrected file instead, before locking)
- CSV support (xlsx only — CSV loses the Text date formatting that stops
  Excel mangling dates)
