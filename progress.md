# progress.md — Gemini ERP Build Log

Living record of what has been built, key decisions, and placeholders that
still need real values. Read this before starting new work so context isn't
lost or re-guessed. See `ROADMAP.md` for the big picture and `CHECKLIST.md`
for the Phase 1 tick-list (now fully complete).

---

## Status: Phase 1 COMPLETE (Milestones 0-5), Phase 2 Part 1 COMPLETE (Milestones 6-9), Phase 2 Part 2 COMPLETE (Milestones 10-19) — PHASE 2 DONE

The core loop works end to end: Item Master -> Sales Invoice (single
transaction, GST split) -> stock auto-deducts -> sale logged -> Sales Log ->
PDF invoice.

Phase 2 Part 1 (the purchase mirror image, see CHECKLIST_PHASE2.md) is also
done: Supplier Master -> Purchase Invoice (single transaction, GST split as
input tax) -> stock auto-increases -> purchase logged -> Purchase Log.

Phase 2 Part 2 (Accounting, Banking & GST Returns, see
CHECKLIST_PHASE2_PART2.md) is COMPLETE: Milestones 10-16 (Chart of Accounts,
auto-posting, Day Book/Ledger, Trial Balance, P&L/Balance Sheet, Outstanding,
Banking core), 18-19 (GST registers/HSN summary, GSTR-1/GSTR-3B), and 17
(bank reconciliation) are all done. Milestone 17 was built LAST, after the GST
returns, per the user's choice. **Phase 2 is now finished end to end.**

---

## Environment

- Venv: `Sopda/venv` (Python 3.14, PySide6 6.11.1, SQLAlchemy 2.0.50,
  ReportLab 4.5.1, OpenPyXL 3.1.5).
- Run app: `cd gemini_erp && ../venv/Scripts/python main.py`
- DB file: `gemini_erp/gemini_erp.db` (SQLite, gitignored).
- Create/recreate tables: `python create_db.py` (one-time / safe to re-run,
  `create_all` is no-op on existing tables).

---

## What exists, by milestone

### Milestone 0/1 — Setup + DB foundation
- `database.py` — SQLAlchemy engine/session for SQLite (`get_session()`),
  written database-neutral for the future MSSQL switch (Phase 4).
- `models/` — 5 core tables, all with `AuditMixin`
  (`created_date, created_by, modified_date, modified_by, is_deleted`):
  - `item.py` — items (code, name, hsn_code, gst_rate, unit, opening_stock,
    reorder_level)
  - `customer.py` — customers (name, gstin, address, state)
  - `sales_invoice.py` — sales_invoices (invoice_no, date, customer_id,
    taxable_amount, cgst, sgst, igst, total)
  - `sales_invoice_item.py` — sales_invoice_items (invoice_id, item_id,
    quantity, rate, amount, gst_amount)
  - `stock_transaction.py` — stock_transactions (item_id, type IN/OUT,
    quantity, reference_type, reference_id, date)
- Soft delete only (`is_deleted`), never hard-delete rows in app code.

### Milestone 2 — Item Master
- `services/item_service.py` — `ItemService`:
  - `add_item(...)`
  - `list_items()` — does **not** include current stock
  - `get_current_stock(item_id)` — calculated live:
    `opening_stock + sum(IN) - sum(OUT)` from `stock_transactions`
    (SQL `func.sum(...).filter(...)`)
- `ui/item_master.py` — `ItemMasterScreen`. The "Current Stock" column is
  filled by calling `get_current_stock(item_id)` per row in
  `refresh_items()` (NOT pre-joined into `list_items()` — this was an
  explicit refactor).

### Milestone 3 — Core sale loop (most important)
- `services/gst_service.py` — `OUR_STATE = "Andhra Pradesh"`,
  `split_gst(taxable_amount, gst_rate, customer_state)`:
  same state -> CGST+SGST (half each), different state -> full rate as IGST.
  Uses `Decimal` + `ROUND_HALF_UP`, quantized to 2 decimals.
- `services/customer_service.py` — `CustomerService`: `add_customer()`,
  `list_customers()`.
- `services/sales_service.py` — `SalesService.create_invoice(invoice_no,
  invoice_date, customer_id, lines, created_by=None)`: ONE transaction —
  invoice header + line items + one OUT `stock_transaction` per line,
  commit or full rollback.
- `ui/billing.py` — `BillingScreen`: header (invoice no/date/customer),
  inline "New Customer" box, item/qty/rate line entry, live GST totals,
  "Save Invoice" button.

### Milestone 4 — PDF invoice
- `reports/company_info.py` — **PLACEHOLDER VALUES, edit before real use**:
  - `COMPANY_NAME`, `COMPANY_ADDRESS`, `COMPANY_MOBILE`, `COMPANY_GSTIN`,
    `COMPANY_STATE`
  - `BANK_NAME`, `BANK_ACCOUNT_NO`, `BANK_IFSC`, `BANK_BRANCH`
  - `TERMS_AND_CONDITIONS` (list of strings, printed as numbered list) —
    these two default lines are real/intended:
    "Goods once sold will not be taken back or exchanged." /
    "All disputes are subject to local jurisdiction only."
- `reports/amount_in_words.py` — `amount_to_words(amount)`: Indian
  numbering (lakh/crore), e.g. "Forty Nine Thousand Four Hundred and
  Seventy Five Rupees Only". Pure stdlib, no external deps.
- `reports/invoice_pdf.py` — `generate_invoice_pdf(invoice_id, output_path)`:
  A4 Tax Invoice — seller header (incl. mobile), invoice/customer info,
  line items table (Item Code, Name, HSN, Qty, Unit, Rate, Amount, GST),
  Amount in Words + Bank Details (left) next to totals box (right),
  Terms & Conditions + signature area at the bottom.
- `ui/billing.py` — "Print / Save PDF" button, disabled until an invoice is
  saved in that session; opens a file dialog and renders the just-saved
  invoice.

### Milestone 5 — Sales log
- `services/sales_service.py` additions:
  - `list_invoices()` — id, invoice_no, date, customer_name, taxable_amount,
    cgst, sgst, igst, total — newest first.
  - `get_invoice_details(invoice_id)` — header + customer info + per-line
    item_code/item_name/quantity/rate/amount/gst_amount.
- `ui/sales_log.py` (new) — `SalesLogScreen` (table of all invoices) +
  `InvoiceDetailDialog` (double-click a row -> header, line items, totals,
  and its own "Print / Save PDF" button reusing `generate_invoice_pdf`).
- `main.py` — three tabs at end of Phase 1: Items, Billing, Sales Log.
  (Now five tabs after Phase 2 Part 1, see below.)

---

## Phase 2 Part 1 — Purchases (mirror of Phase 1). See CHECKLIST_PHASE2.md

### Milestone 6 — Supplier Master
- `models/supplier.py` (new) — `Supplier` (mirrors `Customer`): name, gstin,
  address, state + audit columns. `purchase_invoices` relationship added
  once `PurchaseInvoice` existed (Milestone 7).
- `services/supplier_service.py` (new) — `SupplierService`: `add_supplier()`,
  `list_suppliers()` (mirrors `CustomerService`).
- `create_db.py` updated to import/create the `suppliers` table.
- `check_milestone6.py` — repeatable, adds/finds "Check Supplier Pvt Ltd"
  (Karnataka, GSTIN 29ABCDE1234F1Z5). PASS.

### Milestone 7 — Purchase Invoice core loop (mirror of Milestone 3)
- `models/purchase_invoice.py` (new) — `PurchaseInvoice`: invoice_no (NOT
  unique - it's the supplier's own number), date, supplier_id,
  taxable_amount, cgst, sgst, igst, total + audit.
- `models/purchase_invoice_item.py` (new) — `PurchaseInvoiceItem`:
  invoice_id, item_id, quantity, rate, amount, gst_amount + audit.
- `models/item.py` — added `purchase_lines` relationship.
- `models/supplier.py` — added `purchase_invoices` relationship.
- `models/__init__.py` / `create_db.py` updated to register/create both new
  tables (`purchase_invoices`, `purchase_invoice_items`).
- `services/purchase_service.py` (new) — `PurchaseService`:
  - `create_purchase_invoice(invoice_no, invoice_date, supplier_id, lines,
    created_by=None)` — ONE transaction: header + line items + one IN
    `stock_transaction` per line (`reference_type='PURCHASE'`). Reuses
    `gst_service.split_gst()` with the supplier's state (same state ->
    CGST+SGST, different state -> IGST; represents input tax credit).
  - `list_purchase_invoices()`, `get_purchase_invoice_details(invoice_id)`
    (added in this milestone, used by Milestone 9).
- `check_milestone7.py` — repeatable, mirrors `check_milestone3.py`. Creates
  "Check AP Supplier" (Andhra Pradesh, CGST+SGST) and "Check Karnataka
  Supplier" (Karnataka, IGST), buys 10 + 5 units of `CHK-M2-001`, asserts
  stock goes UP by 10 then 5, and that invoice/line/stock rows exist with
  `type='IN'`. PASS.

### Milestone 8 — Purchase entry UI
- `ui/purchase.py` (new) — `PurchaseScreen` (mirrors `BillingScreen`):
  header (supplier invoice no / date / supplier combo), inline "New
  Supplier" box, item/qty/rate line entry, live GST totals (Taxable/CGST/
  SGST/IGST/Total), "Save Purchase" button. No PDF button - we receive the
  supplier's bill, we don't generate one.
- `main.py` — added `PurchaseScreen` as a "Purchases" tab;
  `on_tab_changed()` now also calls `purchase_screen.refresh_lookups()`.
- Verified with a temporary headless PySide6 script (offscreen platform,
  monkeypatched QMessageBox) that selected item `CHK-M2-001` + supplier
  "Check AP Supplier", added a 3-unit line, saved as `CHK-M8-UI-001`, and
  confirmed stock increased by 3. Script deleted after passing (same
  approach as the Milestone 4 PDF-button check).

### Milestone 9 — Purchase log
- `ui/purchase_log.py` (new) — `PurchaseLogScreen` (table of all purchase
  invoices) + `PurchaseInvoiceDetailDialog` (double-click a row -> header,
  line items, totals). Mirrors `ui/sales_log.py` but with no PDF button.
- `main.py` — added `PurchaseLogScreen` as a "Purchase Log" tab;
  `on_tab_changed()` now also calls `purchase_log_screen.refresh_invoices()`.
  **Tabs are now: Items, Billing, Purchases, Sales Log, Purchase Log.**
- `check_milestone9.py` — repeatable, mirrors `check_milestone5.py`. Reads
  back `CHK-M7-001` / `CHK-M7-002` via `list_purchase_invoices()` /
  `get_purchase_invoice_details()` and asserts supplier names, totals, and
  line details. Depends on `check_milestone7.py` having run first. PASS.
- Verified with a temporary headless `MainWindow` smoke test (offscreen) -
  confirmed all 5 tab titles and that `on_tab_changed()` runs without error.
  Script deleted after passing.

---

## Phase 2 Part 2 — Accounting, Banking & GST Returns. See CHECKLIST_PHASE2_PART2.md

### Milestone 10 — Chart of Accounts (foundation)
- `models/ledger_account.py` (new) - `LedgerAccount`: name, code (nullable
  unique, used for system accounts), account_type (ASSET/LIABILITY/INCOME/
  EXPENSE/EQUITY), account_group (display string, e.g. "Sundry Debtors",
  "Duties & Taxes"), customer_id / supplier_id (nullable FKs),
  opening_balance, opening_balance_type ('Dr'/'Cr', default 'Dr') + audit.
  (`bank_account_id` FK was added later in Milestone 16 alongside the
  `bank_accounts` table.)
- `models/journal_entry.py` (new) - `JournalEntry`: date, reference_type
  ('SALE'/'PURCHASE'/'RECEIPT'/'PAYMENT'/'OPENING'/'JOURNAL'), reference_id
  (nullable), narration (nullable) + audit.
- `models/journal_entry_line.py` (new) - `JournalEntryLine`: entry_id (FK
  journal_entries), account_id (FK ledger_accounts), debit, credit + audit.
- `models/customer.py` / `models/supplier.py` - added a one-to-one
  `ledger_account` relationship back-ref.
- `services/chart_of_accounts.py` (new) - system account codes (`SALES`,
  `PURCHASE`, `CASH`, `CGST_OUTPUT`, `SGST_OUTPUT`, `IGST_OUTPUT`,
  `CGST_INPUT`, `SGST_INPUT`, `IGST_INPUT`) in `SYSTEM_ACCOUNTS`, and
  `ensure_system_accounts(session)` - idempotent seed (skips codes that
  already exist), commits on the passed-in session.
- `services/accounting_service.py` (new) - `AccountingService`:
  `get_account_by_code(session, code)` (static) - looks up a system account
  by `code`, raises `ValueError` if missing. `post_journal_entry()` and the
  sales/purchase posting hooks come in Milestone 11.
- `services/customer_service.py` `add_customer()` / `services/
  supplier_service.py` `add_supplier()` - now also create a linked
  `LedgerAccount` in the SAME transaction (group "Sundry Debtors"/ASSET for
  customers, "Sundry Creditors"/LIABILITY for suppliers; `session.flush()`
  first to get the new customer/supplier id for the FK, then one commit).
- `create_db.py` - creates the 3 new tables and calls
  `ensure_system_accounts()` on a fresh session after `create_all`.
- `check_milestone10.py` - repeatable. Runs `ensure_system_accounts()` twice
  and asserts the system-account count stays at 9 (no duplicates); adds (or
  finds) "Check M10 Customer" / "Check M10 Supplier" and confirms each has a
  linked `ledger_accounts` row with the correct group/type ("Sundry
  Debtors"/ASSET, "Sundry Creditors"/LIABILITY); confirms
  `get_account_by_code()` returns the `SALES` account (INCOME / "Sales
  Accounts") and raises `ValueError` for an unknown code. PASS.

### Milestone 11 — Accounting engine: auto-posting for Sales & Purchase
- `services/accounting_service.py` - added `AccountingService.
  post_journal_entry(session, date, reference_type, reference_id, lines,
  narration=None, created_by=None) -> JournalEntry`. Validates
  `sum(debit) == sum(credit)` (raises `ValueError` if not). Creates a
  `JournalEntry` row, flushes to get its id, then adds `JournalEntryLine`
  rows. Operates on the **passed-in session only** — no own commit, so it
  runs inside the caller's transaction (the "one transaction = all or
  nothing" rule).
- `services/sales_service.py` `create_invoice()` - after computing totals and
  before `session.commit()`, now calls `post_journal_entry()` with:
  ```
  Dr <Customer's ledger account>   total
     Cr Sales Account               taxable_amount
     Cr CGST Output                 cgst    (only if > 0)
     Cr SGST Output                 sgst    (only if > 0)
     Cr IGST Output                 igst    (only if > 0)
  ```
  reference_type='SALE', reference_id=invoice.id. Raises `ValueError` if the
  customer has no linked ledger account (i.e. was created before M10 shipped).
- `services/purchase_service.py` `create_purchase_invoice()` - mirrors the
  above:
  ```
  Dr Purchase Account              taxable_amount
  Dr CGST Input                    cgst    (only if > 0)
  Dr SGST Input                    sgst    (only if > 0)
  Dr IGST Input                    igst    (only if > 0)
     Cr <Supplier's ledger account>   total
  ```
  reference_type='PURCHASE'.
- `check_milestone11.py` (new, repeatable) - creates fixtures `CHK-M11-CUST`
  (AP customer), `CHK-M11-SUPP` (AP supplier), `CHK-M11-ITEM` (18% GST).
  Posts a sale (10 × 100 = 1000 taxable, CGST 90, SGST 90, total 1180) and a
  purchase (20 × 50 = 1000 taxable, CGST 90, SGST 90, total 1180). Asserts:
  each journal entry has balanced lines (sum debit == sum credit); customer
  ledger debit +1180; Sales Account credit +1000; CGST/SGST Output credit +90
  each; supplier ledger credit +1180; Purchase Account debit +1000; CGST/SGST
  Input debit +90 each. PASS.

---

## Follow-up — Inline "Add New Item" on the Purchase screen

- `services/item_service.py` `add_item()` - now rejects a duplicate
  (non-deleted) item `code` with `ValueError`, shared by the Items page and
  the new dialog below.
- `ui/purchase.py` - new `AddItemDialog` (QDialog): Code, Name, HSN Code,
  GST Rate (%), Unit, Reorder Level (opening_stock fixed at 0 - stock for a
  new item comes from the purchase's IN transaction, not opening stock).
  Saving calls `ItemService.add_item()` - same service as the Items page.
- `PurchaseScreen` - added a "+ New Item" button next to the item picker on
  the line-entry row. On save, `refresh_lookups()` repopulates `item_combo`
  and the new item is auto-selected so the user can continue entering
  qty/rate on that line.
- `check_inline_item.py` (new, repeatable) - confirms `add_item()` creates
  exactly one `items` row, the item appears via `list_items()` (same data as
  the Items page), a duplicate code raises `ValueError`, and recording a
  purchase for the new item writes an IN `stock_transaction` so current
  stock equals the purchased quantity. PASS.
- Verified the dialog -> refresh -> auto-select wiring with a temporary
  headless smoke test (offscreen, fake ItemService so it doesn't touch the
  real DB) - script deleted after passing, same approach as the Milestone
  4/8 UI checks.

---

## Known issues / deliberate non-fixes

- **`check_milestone2.py` is broken and intentionally left as-is.** It tries
  to delete-and-recreate item `CHK-M2-001` (id=1) for a clean re-run, but
  that item now has real FK references from real invoices (e.g.
  `DA001/2026-2027`, `DA039/2026-2027`) created via the actual app. User
  instruction: "Leave it we would use to verify once complete app is built."
  Do not modify this script without asking first.
- `check_milestone3.py`, `check_milestone4.py`, `check_milestone5.py` are
  all repeatable (they reset/reuse `CHK-M3-001` / `CHK-M3-002`) and pass.
  `check_milestone4/5` depend on `check_milestone3` having been run at least
  once (to create those two invoices).
- `check_milestone6.py`, `check_milestone7.py`, `check_milestone9.py` are
  all repeatable (they reset/reuse `CHK-M7-001` / `CHK-M7-002` and "Check
  Supplier Pvt Ltd" / "Check AP Supplier" / "Check Karnataka Supplier") and
  pass. `check_milestone9` depends on `check_milestone7` having been run at
  least once. There is no `check_milestone8.py` - Milestone 8 (Purchase
  entry UI) was verified with a temporary headless script that was deleted,
  same as the Milestone 4 PDF-button check.
- PDFs generated by check scripts go to `gemini_erp/output/` (gitignored) —
  clean up after manual test runs.

---

## Placeholders that need real values before going live

In `gemini_erp/reports/company_info.py`:
- `COMPANY_NAME` = "Your Company Name"
- `COMPANY_ADDRESS`, `COMPANY_MOBILE`, `COMPANY_GSTIN`, `COMPANY_STATE`
- `BANK_NAME`, `BANK_ACCOUNT_NO`, `BANK_IFSC`, `BANK_BRANCH`

A real sample invoice (`DA039/2026-2027`, seller "DEEPAK AGENCIES", Kurnool,
GSTIN `37KYIPK4025F1ZA`) was shown during this session as a layout
reference — user explicitly chose to KEEP placeholders in the repo for now
rather than commit real business/bank details. Real data lives only in the
user's local `gemini_erp.db` from manual app testing (not in git).

---

## Real usage data already in the dev DB (not test data)

The user has been testing the built app independently. The dev SQLite DB
contains real-ish records, including:
- Customer id=3, items `CHK-M2-001` / `CHK-M2-002`
- Invoices `DA001/2026-2027`, `DA039/2026-2027` (referenced in the sample
  PDF discussion)

This is why `check_milestone2.py`'s cleanup logic now fails (see above) —
treat this as real data, not disposable test fixtures.

As of Milestone 10, the dev DB also has: 9 seeded system `ledger_accounts`
rows (`SALES`, `PURCHASE`, `CASH`, `CGST_OUTPUT`, `SGST_OUTPUT`,
`IGST_OUTPUT`, `CGST_INPUT`, `SGST_INPUT`, `IGST_INPUT`), plus one
`ledger_accounts` row per existing customer/supplier created going forward
(and the "Check M10 Customer" / "Check M10 Supplier" fixtures + their linked
ledger accounts). Per Decision 2 in `CHECKLIST_PHASE2_PART2.md`, none of the
pre-Milestone-11 invoices have journal entries — that starts in Milestone 11.

---

## Next up: Phase 3 (Phase 2 is complete)

All of Phase 2 Part 2 (Milestones 10-19) is done — see the milestone sections
below. Per `ROADMAP.md`, Phase 3 (OCR, Document Management, AI Reporting) is
next; plan it separately when the time comes. No Phase 2 work remains.

### Milestone 12 — Day Book & Ledger view
- `services/accounting_service.py` additions:
  - `list_accounts() -> list[dict]` — all non-deleted ledger accounts ordered
    by account_type then name, for the account picker UI.
  - `get_day_book(date_from, date_to) -> list[dict]` — journal entries in
    range (newest first) with their lines (account_name, debit, credit).
  - `get_ledger(account_id, date_from=None, date_to=None) -> dict` —
    opening balance, dated entries with running balance, closing balance.
    Running balance convention: positive = Dr, negative = Cr (sign is internal
    only; the returned dict always shows `abs(running)` + `"Dr"/"Cr"` string).
- `ui/day_book.py` (new) — `DayBookScreen`: date range pickers + Refresh
  button + `QTreeWidget` (entry rows as parent nodes, line rows as children
  showing account name / debit / credit).
- `ui/ledger_view.py` (new) — `LedgerViewScreen`: account `QComboBox` +
  date range + Refresh button + opening label + `QTableWidget` (Date /
  Narration / Debit / Credit / Balance) + closing label. `refresh_accounts()`
  repopulates the combo (called from `main.py` on every tab change so new
  customers/suppliers appear).
- `main.py` — added `DayBookScreen` and `LedgerViewScreen` inside a nested
  `QTabWidget` under a new "Accounts" top-level tab. Window size bumped to
  1200×800. `on_tab_changed()` now also calls
  `ledger_view_screen.refresh_accounts()`.
- `check_milestone12.py` (new, repeatable, depends on M11 fixtures):
  Day Book for M11 sale date contains the SALE entry (4 balanced lines) and
  PURCHASE entry; Sales Account ledger shows credit 1000.00, closing 1000.00 Cr;
  customer ledger shows debit 1180.00, balance 1180.00 Dr; `list_accounts()`
  returns 16 accounts including all system codes. PASS.

### Milestone 13 — Trial Balance
- `services/accounting_service.py` — `get_trial_balance(as_of_date=None) ->
  list[dict]`. Sums journal_entry_line debits/credits per account (filtered by
  date via journal_entries join), adds opening_balance, shows net on natural
  side (Dr in debit col, Cr in credit col); zero-balance accounts excluded.
  Sorting: account_type then name.
- `ui/trial_balance.py` (new) — `TrialBalanceScreen`: as-of date picker +
  Refresh + `QTableWidget` (Account / Group / Debit / Credit) + totals row
  showing "BALANCED" if total debit == total credit (within 0.01).
- `main.py` — added `TrialBalanceScreen` as "Trial Balance" sub-tab under
  "Accounts".
- `check_milestone13.py` (new, repeatable, depends on M11 fixtures): Trial
  balance for M11 fixture date: total Dr 2360.00 == total Cr 2360.00 (BALANCED);
  CHK-M11-CUST Dr 1180, CHK-M11-SUPP Cr 1180, Sales Account Cr 1000, Purchase
  Account Dr 1000, CGST Output Cr 90, CGST Input Dr 90. PASS.

### Milestone 14 — Profit & Loss and Balance Sheet
- `services/accounting_service.py` additions:
  - Private `_line_totals_by_account(session, date_from=None, date_to=None) ->
    dict` helper — reused by both P&L and Balance Sheet to avoid duplicate
    query logic.
  - `get_profit_and_loss(date_from, date_to) -> dict` — INCOME accounts
    (amount = Cr - Dr), EXPENSE accounts (amount = Dr - Cr), net_profit.
    **Known limitation (documented inline and in CHECKLIST_PHASE2_PART2.md
    Decision 3)**: Purchase Account treated as period expense regardless of
    unsold stock — no Trading Account / COGS yet.
  - `get_balance_sheet(as_of_date=None) -> dict` — assets (net Dr per ASSET
    account), liabilities (net Cr per LIABILITY/EQUITY account),
    net_profit_to_date (sum of all INCOME Cr-Dr minus EXPENSE Dr-Cr). By
    double-entry construction: `sum(assets) == sum(liabilities) +
    net_profit_to_date` always holds.
- `ui/profit_and_loss.py` (new) — `ProfitAndLossScreen`: date range + Refresh
  + income table + expense table + "Net Profit / Net Loss" label.
- `ui/balance_sheet.py` (new) — `BalanceSheetScreen`: as-of date + Refresh +
  assets table + liabilities table (with synthetic "Profit & Loss A/c
  (current)" row for net_profit_to_date) + balance check label.
- `main.py` — added "P & L" and "Balance Sheet" sub-tabs under "Accounts".
- `check_milestone14.py` (new, repeatable, depends on M11): P&L income
  (Sales Account 1000) == expenses (Purchase Account 1000), net_profit = 0;
  Balance Sheet: assets 1360 == liabilities 1360 + net_profit 0 — BALANCED.
  PASS.

### Milestone 15 — Customer / Supplier Outstanding
- `services/accounting_service.py` additions:
  - `get_outstanding_customers() -> list[dict]` — customers with a net Dr
    balance on their ledger account (opening_balance + sum(Dr) - sum(Cr) >
    0). Returns {"customer_id", "name", "gstin", "outstanding"}, sorted by name.
  - `get_outstanding_suppliers() -> list[dict]` — suppliers with a net Cr
    balance (net < 0 from the same formula; reported as abs(net)). Sorted by
    name.
  - Both reuse `_line_totals_by_account()` for all-time totals (no date
    filter — outstanding is a point-in-time snapshot of the full running
    balance).
- `ui/outstanding.py` (new) — `OutstandingScreen`: Refresh button +
  "Customers Outstanding (Receivables)" table (Customer / GSTIN / Outstanding)
  with total receivable label + "Suppliers Outstanding (Payables)" table with
  total payable label.
- `main.py` — added "Outstanding" sub-tab under "Accounts".
- `check_milestone15.py` (new, depends on M11 fixtures with no
  receipts/payments yet): CHK-M11-CUST outstanding 1180.00, CHK-M11-SUPP
  outstanding 1180.00. PASS.

### Milestone 16 — Receipts & Payments (banking core)
- New models (all with `AuditMixin`):
  - `models/bank_account.py` — `BankAccount`: name, bank_name, account_no,
    ifsc, opening_balance. Linked one-to-one to a `LedgerAccount` (group
    "Bank Accounts", `account_type='ASSET'`) via the new
    `ledger_accounts.bank_account_id` FK.
  - `models/receipt.py` — `Receipt`: date, customer_id, payment_mode
    ('CASH'|'BANK'), bank_account_id (nullable, set only for BANK), amount,
    reference_no, notes.
  - `models/payment.py` — `Payment`: mirror with supplier_id.
- `models/ledger_account.py` — added `bank_account_id` nullable FK +
  `bank_account` relationship (back_populates).
- `create_db.py` — added a `_migrate_add_column()` helper that ALTERs in new
  columns on already-existing tables (`create_all` never alters existing
  tables). Used to add `ledger_accounts.bank_account_id` to the dev DB.
  Order: `create_all()` first (builds bank_accounts/receipts/payments), then
  the ALTER (so the FK target exists). Idempotent — checks PRAGMA columns.
- `services/banking_service.py` (new) — `BankingService`:
  - `add_bank_account(...)` / `list_bank_accounts()` — bank account row +
    linked ledger account created in ONE transaction (mirrors customer/
    supplier ledger creation).
  - `record_receipt(date, customer_id, amount, payment_mode,
    bank_account_id=None, reference_no=None, notes=None, ...)` — one
    transaction: `Receipt` row + journal entry `Dr Cash/Bank` / `Cr Customer
    ledger` (`reference_type='RECEIPT'`). CASH posts to the system CASH
    account; BANK posts to the bank's linked ledger account.
  - `record_payment(...)` — mirror: `Dr Supplier ledger` / `Cr Cash/Bank`
    (`reference_type='PAYMENT'`).
  - `list_receipts()` / `list_payments()` — include resolved party + bank
    account names for display.
  - Shared helpers: `_cash_or_bank_account_id()` resolves the asset ledger to
    post against; `_party_ledger_account()` finds the customer/supplier
    ledger. Both raise clear `ValueError`s (e.g. BANK mode with no bank
    account, amount <= 0).
- `ui/banking.py` (new) — `BankingScreen(QTabWidget)` with three sub-tabs:
  - `BankAccountsTab` — add form + list table.
  - `ReceiptsTab` / `PaymentsTab` — share a `_MoneyMoveTab` base (date, party
    combo, amount, mode CASH/BANK, bank-account combo enabled only for BANK,
    reference, notes) + record button + history table.
  - `refresh_all()` repopulates customer/supplier/bank-account combos
    (called from `main.py` on tab change).
- `main.py` — added `BankingScreen` as a new "Banking" top-level tab;
  `on_tab_changed()` now also calls `banking_screen.refresh_all()`.
- `check_milestone16.py` (new, repeatable, self-contained CHK-M16-* fixtures
  so it does NOT disturb the CHK-M11 fixtures M15 asserts on): builds a sale +
  purchase (each 1180), confirms customer/supplier outstanding == 1180, then:
  CASH receipt 1180 → customer outstanding 0, Cash Dr +1180; CASH payment
  1180 → supplier outstanding 0, net Cash delta 0; BANK receipt 500 → bank
  account ledger Dr +500. PASS (idempotent on re-run; M15 still PASS after).

Smaller, optional follow-ups noted but not requested:
- No PO -> GRN -> Purchase Invoice workflow yet; purchases are entered
  directly (mirrors how Phase 1 sales skipped Quotation/Sales Order/Delivery
  Challan too).
- No dedicated Supplier Master *screen* — suppliers are added inline from
  the Purchases tab (mirrors how customers are added inline from Billing).

### Milestone 18 — GST Sales/Purchase Registers + HSN Summary
- `services/gst_report_service.py` (new) — `GstReportService`. A PURE READ
  layer over the raw invoice tables; it does NOT touch the accounting engine,
  so it also sees pre-Milestone-11 invoices (which have no journal entries).
  These are the "type into the GST portal" figures — no e-filing.
  - `get_sales_register(date_from, date_to)` / `get_purchase_register(...)` —
    one row per invoice line: date, invoice_no, party name + GSTIN, hsn_code,
    taxable_amount, cgst, sgst, igst, total.
  - `get_hsn_summary(date_from, date_to, direction='SALES'|'PURCHASE')` —
    grouped by `(hsn_code, gst_rate)`: total quantity, taxable, cgst/sgst/igst,
    total.
  - **Per-line tax split:** invoices store cgst/sgst/igst only at the header.
    The service infers the line split from the invoice — if the invoice has
    IGST it's inter-state (whole line tax = IGST), else it splits the line's
    `gst_amount` into `cgst = round(gst_amount/2)` and `sgst = gst_amount -
    cgst` so a line's CGST+SGST always equals its `gst_amount` exactly (no
    half-paisa drift when aggregating). Shared private helper `_line_rows()`
    feeds both the registers and the HSN summary.
- `ui/gst_reports.py` (new) — `GstReportsScreen`: date range + a view combo
  (Sales Register / Purchase Register / HSN Summary (Sales) / HSN Summary
  (Purchase)) + a totals line + "Export to Excel" (OpenPyXL — first use of
  that dependency; writes the current view to an `.xlsx` via `QFileDialog`).
- `check_milestone18.py` (new, repeatable) — self-contained `CHK-M18-*`
  fixtures on a **sentinel date in FY 2019-20** so the date-filtered reports
  see only the fixtures, never real dev-DB invoices. Covers intra-state
  (CGST/SGST), B2C (no-GSTIN customer), and inter-state (IGST) sales plus an
  intra-state purchase. Asserts register rows and HSN-group totals to the
  paisa. `build_fixtures()` is reused by `check_milestone19.py`. PASS
  (idempotent).

### Milestone 19 — GSTR-1 / GSTR-3B Summary
- `services/gst_report_service.py` additions:
  - `get_gstr1_summary(date_from, date_to)` — `{"b2b": [...per registered-
    customer invoice...], "b2c_small": {aggregated for no-GSTIN customers},
    "hsn_summary": get_hsn_summary(direction='SALES')}`. B2B/B2C use the
    invoice header totals directly (exact).
  - `get_gstr3b_summary(date_from, date_to)` — `outward_taxable_supplies`
    (sales totals, table 3.1a), `itc_available` (purchase tax totals, table 4),
    `net_tax_payable` (output − ITC per head, floored at 0) and
    `itc_carried_forward` (the excess ITC per head when ITC > output).
  - `_invoice_tax_totals()` private helper sums header taxable/cgst/sgst/igst
    over non-deleted invoices in range (used by both outward and ITC).
- `ui/gst_returns.py` (new) — `GstReturnsScreen`: date range + read-only
  GSTR-1 B2B table + B2C-small line + GSTR-3B summary table (outward / ITC /
  net payable / carried forward). Add as the "Returns" sub-tab under "GST".
- `main.py` — new "GST" top-level tab holding a nested `QTabWidget` with
  "Registers/HSN" (M18) and "Returns" (M19) sub-tabs. **Tabs are now: Items,
  Billing, Purchases, Sales Log, Purchase Log, Accounts, Banking, GST.**
  `on_tab_changed()` also refreshes both GST screens.
- `check_milestone19.py` (new, repeatable) — reuses `check_milestone18`'s
  `build_fixtures()`. Asserts GSTR-1 has 2 B2B invoices + B2C small 200/5/5/0,
  and GSTR-3B outward 1700/95/95/90 − ITC 90/90/0 → net payable 5/5/90 with
  nothing carried forward. PASS (idempotent). Verified the GST tab + Excel
  export end-to-end with a temporary headless offscreen smoke test (deleted
  after passing, same approach as the M4/M8 UI checks).

### Milestone 17 — Bank Reconciliation (built last, after 18-19)
- `models/bank_statement_line.py` (new) — `BankStatementLine`: bank_account_id
  (FK), date, description, `amount` (SIGNED: + deposit, − withdrawal),
  is_matched (bool), matched_receipt_id / matched_payment_id (nullable FKs) +
  audit. Registered in `models/__init__.py` and `create_db.py`. Brand-new
  table, so `create_all()` builds it — no ALTER migration needed.
- `services/banking_service.py` additions:
  - `add_statement_line(bank_account_id, date, description, amount, ...)` —
    manual entry only (no file import, Decision 4); rejects a zero amount.
  - `list_unmatched_statement_lines(bank_account_id)` / `list_statement_lines`.
  - `list_unmatched_receipts(bank_account_id)` / `list_unmatched_payments` —
    BANK-mode receipts/payments for that account not yet tied to any statement
    line (shared `_unmatched_money_moves()` helper using a `NOT IN` subquery on
    the matched_*_id columns).
  - `match_statement_line(line_id, receipt_id=None, payment_id=None)` — sets
    is_matched + the relevant matched_*_id. Validates: exactly one of
    receipt/payment id, sign↔kind (deposit→receipt, withdrawal→payment), same
    bank account, equal absolute amounts, and the line isn't already matched.
- `ui/banking.py` — new `ReconciliationTab` (added as a 4th Banking sub-tab,
  so Banking is now Bank Accounts / Receipts / Payments / Reconciliation).
  Pick a bank account, an inline "Add Statement Line" form (signed amount),
  then two side-by-side tables (unmatched statement lines | unmatched
  receipts+payments) and a "Match Selected" button. Row payloads are stashed
  on the first cell via `Qt.UserRole`. `BankingScreen.refresh_all()` also
  refreshes this tab. **No new top-level tab** — it lives under Banking.
- `check_milestone17.py` (new, repeatable, self-contained `CHK-M17-*`
  fixtures): records a BANK receipt (750) + BANK payment (300), adds a +750
  deposit line and a −300 withdrawal line, matches each to its move, and
  asserts is_matched flips + the items leave the unmatched lists. Also asserts
  the four validation guards raise (wrong sign, both ids, re-match, amount
  mismatch). PASS (idempotent). The match flow was also exercised through the
  actual `ReconciliationTab` widgets in a temporary headless offscreen smoke
  test (deleted after passing).

**Phase 2 Part 2 is DONE** — every sale/purchase auto-posts to the books, the
Trial Balance balances to the paisa, P&L / Balance Sheet / Outstanding work,
receipts/payments record against party balances and reconcile against manually
entered bank statement lines, and the GST register/HSN/GSTR-1/GSTR-3B numbers
are available (with Excel export). Phase 2 (per `ROADMAP.md`) is complete.

---

## Post-Phase-3 enhancements (edit features) — 2026-07-10

Found during testing; see `CHECKLIST_ENHANCEMENTS.md` for the full checklist.

- **Edit item master** — `ItemService.update_item()` (code stays unique,
  stock stays derived) + edit mode in `ui/item_master.py`. Test:
  `check_item_edit.py` PASS.
- **Edit a saved purchase invoice** — `PurchaseService.update_purchase_invoice()`
  reverses the original IN stock + journal entry (soft-delete) and re-applies
  the edited ones in **one transaction**; shared `_apply_lines_and_accounting`
  helper is reused by create + update. Wired from the Purchase Log
  (`edit_requested` signal → `main.py` → `PurchaseScreen.load_invoice_for_edit`).
  Test: `check_purchase_edit.py` PASS (net stock, single active txn/journal/line,
  trial balance still balances).
- **Edit a billing line before saving** — in-memory replace in `ui/billing.py`
  (and the same on the Purchase grid, needed by the invoice edit). Test:
  `check_edit_ui.py` (offscreen Qt) PASS.

Regression: `check_milestone11` (purchase accounting) + `check_milestone18`
(GST registers) still PASS after refactoring `create_purchase_invoice`.

---

## Phase 4 — Going multi-user (see CHECKLIST_PHASE4.md)

### Milestone 24 — SQL Server migration (config-driven DB) — DONE 2026-07-30
- `database.py` reads `GEMINI_DB_URL` from `.env` (python-dotenv), falling back
  to the local SQLite file. One code path, two backends. Fixed 4 MSSQL
  incompatibilities (no logic change): `.is_(False)`→`== false()`; nullable
  UNIQUE `ledger_accounts.code`→filtered unique index; aggregate `FILTER`→
  `SUM(CASE WHEN…)`; `stock_transactions.date` `DateTime`→`Date`. `reset_dev_db.py`
  added. Parity verified. SQL Server = `HP\GEMINI`, Windows auth, ODBC Driver 17.

### check_milestone2 cleanup — DONE 2026-07-30
- The long-broken `check_milestone2.py` is now fixed (NOTE: this supersedes the
  "broken and intentionally left as-is" entry under Known issues above).
  `ItemService.list_items()` again returns `current_stock` (derived in one
  grouped query; the Items page dropped its per-row N+1). The check uses a
  unique per-run item code — no hard delete, so no soft-delete violation and no
  FK cascade on MSSQL. PASS both backends.

### Milestone 25 — Company profile, Settings & Backup — DONE 2026-07-30
- `models/company_profile.py` (single-row) + `SettingsService`; seller/bank/terms
  now come from the DB, edited on the new **Settings** tab (`ui/settings.py`).
  `reports/company_info.py` is seed-defaults only. `BackupService`: SQLite file
  copy / MSSQL `BACKUP DATABASE`+`RESTORE VERIFYONLY` (raw pyodbc cursor —
  SQLAlchemy silently no-ops BACKUP). `check_milestone25.py` PASS both backends.

### Milestone 26 — Users, Roles & AuthService — DONE 2026-07-30
- `models/role.py` (permissions = JSON-string Text), `models/user.py`
  (`password_hash` only — NO plaintext `password` column ever), both + audit.
- `services/permissions.py` — module keys + the 4 role permission sets (single
  source of truth for UI and service).
- `services/auth_service.py` — bcrypt via passlib (`bcrypt==4.0.1` PINNED;
  passlib 1.7.4 breaks on 4.1+). `authenticate()` uses timing-safe `verify()` and
  returns `None` identically for unknown-user and wrong-password. Passwords/hashes
  never logged. `ensure_roles_and_admin()` seeds the 4 roles + a default admin
  (`admin`/`Admin@1234`, `must_change_password=True`) only on an empty users
  table; idempotent, wired into `create_db`. `check_milestone26.py` PASS both
  backends.

### Milestone 27 — Login + RBAC — DONE 2026-07-30
- `services/session_context.py` — process-wide current user (`get_username()`
  → "system" when logged out). `ui/login.py` (generic error, masked password,
  5-attempt/30s lockout, Enter submits), `ui/change_password.py` (forced,
  non-cancellable when `must_change_password`), `ui/user_management.py`
  (Administrator-only; never shows a hash).
- `main.py` — startup flow: bootstrap → login → forced password change →
  MainWindow. Tabs are built ONLY for permitted modules (a disallowed screen is
  never constructed, not hidden). Title shows `name (role)`. **Account → Logout**
  returns to the login screen without restarting (main runs a login/exec loop).
- `created_by`/`modified_by` wired to `SessionContext.get_username()` at every
  saving UI call site (billing, purchase incl. edit + inline item/supplier,
  items, banking receipt/payment/bank-account, OCR document save). Service
  signatures unchanged — services stay unaware of the logged-in user.
- `check_milestone27.py` PASS both backends (RBAC per-role module sets,
  created_by wiring, SessionContext default, admin_reset_password). RBAC tab
  construction also verified with an offscreen MainWindow smoke test per role
  (deleted after passing, same approach as prior UI checks).

### Known limitations (M26/M27 — out of scope, by design)
- **Tab-level permissions only** — a role either sees a screen or it does not.
  No read-only vs edit granularity within a screen yet.
- No password reset by email (no email infra); no password expiry/history rules;
  no two-factor auth.
- Windows/AD integrated auth not used — the decision was app-level users with
  hashed passwords (portable across SQLite/MSSQL).
- Default admin credential is `admin`/`Admin@1234` on a fresh DB; it is forced
  to change on first login. Change it before any real deployment.

### Milestone 28 — Concurrency hardening & multi-user deployment — DONE 2026-07-30
- **Decisions (user):** oversell = **allow but warn**; invoice numbering = **keep
  manual entry** (no auto-generation).
- `SalesService.create_invoice`: catches `IntegrityError` from the existing
  `UNIQUE(sales_invoices.invoice_no)` and raises a friendly "Invoice number '…'
  is already used" `ValueError` — race-safe manual numbering (the constraint is
  the authority; two clients saving the same number → one wins, one clean
  rejection). Also computes a non-blocking negative-stock warning after commit
  and attaches it as a transient `invoice.stock_warnings` (not a DB column);
  Billing shows it after saving. `purchase_invoices.invoice_no` stays NON-unique
  (supplier's own number).
- `README.md` — new "Multi-user deployment (LAN + concurrency)" section:
  per-client `.env` + ODBC driver, shared-server first-run, concurrency
  behavior, VPN-only remote access, packaging pointer. Default READ COMMITTED is
  correct (one sale = one transaction).
- `check_milestone28.py` (threads, each own session) PASS both backends:
  (A) duplicate-number race → 1 saved / 1 rejected / 1 row; (B) N concurrent
  sales → no lost updates + N OUT rows; (C) oversell commits + warns (stock < 0).
- Packaging (PyInstaller onedir + Inno installer) was already built earlier; no
  new packaging code this milestone.
- Remaining Phase 4 item: **M29 (mobile companion).** Approach LOCKED: read-first
  PWA over FastAPI, JWT auth, backend-first (see CHECKLIST_PHASE4 Decision 5).

### Milestone 29a — FastAPI read API — DONE 2026-07-30
- New `requirements-api.txt` (fastapi/uvicorn/PyJWT/httpx) — SEPARATE from the
  desktop reqs; all install clean on the 3.14 venv. New `gemini_erp/api/` package
  reusing the existing services (no logic duplication):
  - `config.py` — `GEMINI_JWT_SECRET` (dev fallback + warning), TTL, CORS from env.
  - `auth.py` — `POST /api/auth/login` → JWT (via `AuthService.authenticate`);
    `get_current_user` (HTTPBearer, re-loads the live user each request),
    `require_permission(module_key)` dep, `GET /api/me`, in-memory 5/30s login
    rate-limit → 429. Same generic error as desktop.
  - `routers/` — dashboard (per-permission metrics; disallowed = null),
    outstanding (accounts), stock + /reorder (items), invoices/recent
    (sales_log), gst/gstr3b (gst). `main.py` = app + CORS + `/api/health`.
- Run: `cd gemini_erp && uvicorn api.main:app` (reads the same GEMINI_DB_URL;
  set GEMINI_JWT_SECRET). Swagger at `/docs`. README "Mobile companion API".
- `check_milestone29.py` (FastAPI TestClient) PASS both backends: login 401
  (generic) / no-token 401 / RBAC 200-403 per role / dashboard hides receivables
  from a Sales User / rate-limit 429 / numbers match the desktop services. Live
  uvicorn run also verified (health 200).
- Next: M29b (installable PWA over this API, HTTPS/VPN) — front-end work.

### Milestone 29c — Approve-a-scanned-bill (the one API write) — DONE 2026-07-30
- Manager sign-off on scanned supplier bills. `models/document.py`: nullable
  `approval_status` (PENDING/APPROVED/REJECTED, ORM default PENDING; NULL on old
  rows treated as PENDING), `approved_by`, `approved_date`, `approval_note`.
  Migrated onto existing tables via `_migrate_add_column`, now **backend-aware**
  (`ADD` on SQL Server vs `ADD COLUMN` on SQLite — this also fixed a latent MSSQL
  bug in that helper, which had never fired because prior columns were built by
  create_all on the fresh MSSQL DB).
- `DocumentService.set_approval(id, decision, approved_by, note)` (one txn;
  validates decision; not-found -> ValueError). `list_documents` returns the
  approval fields via a shared `_to_dict`.
- `api/routers/documents.py` (module `documents`): `GET /api/documents`
  (+ `?approval_status=`), `POST /api/documents/{id}/approve|reject`; records the
  JWT user as approved_by. Honest scope: approve = review sign-off, NOT invoice
  creation (that needs the desktop's interactive item mapping).
- `check_milestone29c.py` (FastAPI TestClient) PASS both backends: list/approve/
  reject persist; Sales User 403 (no `documents`); missing doc 404. Regression
  M22/M23 (OCR/documents) + M29a still PASS.
- **Phase 4 is functionally complete except M29b (the PWA front-end).** All
  backend milestones (M24 MSSQL, M25 settings/backup, M26/27 auth+RBAC, M28
  concurrency, M29a API, M29c write) are done and tested on both backends.
