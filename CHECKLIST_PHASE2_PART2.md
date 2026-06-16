# CHECKLIST_PHASE2_PART2.md — Phase 2 Part 2: Accounting, Banking & GST Returns

PLANNING DOCUMENT — nothing in this file has been built yet. Phase 2 Part 1
(Supplier Master + Purchases, Milestones 6-9, `CHECKLIST_PHASE2.md`) is done.
This is the remaining Phase 2 scope from `ROADMAP.md`:

- Accounting engine (auto journal entries for each sale/purchase)
- Ledgers, Day Book, Trial Balance, Profit & Loss, Balance Sheet
- Customer/Supplier outstanding
- Banking: receipts, payments, reconciliation
- GST registers and returns (GSTR-1, GSTR-3B, HSN summary)

Same rule as always: **build -> test -> confirm -> next, one milestone at a
time.** Milestone numbering continues from Phase 2 Part 1 (next is 10).

---

## Decisions already made (do not re-litigate without asking)

1. **Per-party ledger accounts.** Every customer and every supplier
   automatically gets its own row in `ledger_accounts` (group "Sundry
   Debtors" / "Sundry Creditors"). Outstanding = that account's balance.
   This is the Tally-style approach and gives customer/supplier statements
   for free via the Ledger view (Milestone 12).
2. **No backfill of historical invoices.** The accounting engine only posts
   journal entries for sales/purchase invoices created AFTER Milestone 11
   ships. The existing invoices in `gemini_erp.db` (DA001, DA039, CHK-M3-*,
   CHK-M7-*, etc.) stay as billing/inventory records but never appear in the
   books. Milestones 11-19's own check scripts create fresh fixtures
   (`CHK-M11-*` etc.) for accounting tests.
3. **Simple P&L for now (no Trading Account / COGS).** Milestone 14's P&L
   treats the whole "Purchase Account" balance as a period expense, with no
   adjustment for unsold closing stock. This is a known simplification - see
   Milestone 14 for details. A proper Trading Account needs item cost/
   valuation, which doesn't exist yet. Revisit later; not a blocker now.
4. **No bank statement import.** Per `Instructions_Claude.txt`, statement
   import is explicitly "Future Scope". Milestone 17 (reconciliation) uses
   manually-entered statement lines only.

---

## New tables (7), at a glance

| Table | Milestone | Purpose |
|---|---|---|
| `ledger_accounts` | 10 | Chart of accounts (system accounts + one per customer/supplier/bank account) |
| `journal_entries` | 10/11 | Double-entry transaction header (date, reference, narration) |
| `journal_entry_lines` | 10/11 | Debit/credit lines per journal entry |
| `bank_accounts` | 16 | Our bank accounts, each linked to a ledger account |
| `receipts` | 16 | Money received from customers |
| `payments` | 16 | Money paid to suppliers |
| `bank_statement_lines` | 17 | Manually-entered bank statement rows for matching |

New services: `accounting_service.py` (10-15), `banking_service.py` (16-17),
`gst_report_service.py` (18-19).

## UI organization

Phase 1 + Part 1 already use 5 flat tabs (Items, Billing, Purchases, Sales
Log, Purchase Log). Adding ~10 more screens flat would be unusable. Group
new screens into nested `QTabWidget`s under three new top-level tabs, matching
the nav structure in `Instructions_Claude.txt`:

- **Accounts** tab -> sub-tabs: Day Book, Ledger, Trial Balance, P&L,
  Balance Sheet, Outstanding
- **Banking** tab -> sub-tabs: Bank Accounts, Receipts, Payments,
  Reconciliation
- **GST** tab -> sub-tabs: Registers/HSN, Returns

---

## Milestone 10 — Chart of Accounts (foundation)

- [ ] `models/ledger_account.py` — `LedgerAccount`: `id`, `name`,
      `code` (nullable, unique string for system accounts, e.g. `"SALES"`,
      `"CGST_OUTPUT"`), `account_type` (`'ASSET' | 'LIABILITY' | 'INCOME' |
      'EXPENSE' | 'EQUITY'`), `account_group` (display string, e.g. "Sundry
      Debtors", "Duties & Taxes"), `customer_id` (nullable FK), `supplier_id`
      (nullable FK), `bank_account_id` (nullable FK, added in Milestone 16),
      `opening_balance` (Numeric, default 0), `opening_balance_type`
      (`'Dr' | 'Cr'`, default `'Dr'`) + audit columns
- [ ] `models/journal_entry.py` — `JournalEntry`: `id`, `date`,
      `reference_type` (`'SALE' | 'PURCHASE' | 'RECEIPT' | 'PAYMENT' |
      'OPENING' | 'JOURNAL'`), `reference_id` (nullable Integer),
      `narration` (nullable String) + audit columns
- [ ] `models/journal_entry_line.py` — `JournalEntryLine`: `id`,
      `entry_id` (FK journal_entries), `account_id` (FK ledger_accounts),
      `debit` (Numeric, default 0), `credit` (Numeric, default 0) + audit
      columns
- [ ] `services/chart_of_accounts.py` — module of constants for system
      account codes (`SALES`, `PURCHASE`, `CASH`, `CGST_OUTPUT`,
      `SGST_OUTPUT`, `IGST_OUTPUT`, `CGST_INPUT`, `SGST_INPUT`, `IGST_INPUT`)
      + a seed function `ensure_system_accounts(session)` that creates any
      missing system accounts (idempotent - safe to call every app start or
      from `create_db.py`)
- [ ] `services/accounting_service.py` (new) —
      `AccountingService.get_account_by_code(session, code) ->
      LedgerAccount` (looks up a system account by `code`, raises if missing)
- [ ] Update `services/customer_service.py` `add_customer()` and
      `services/supplier_service.py` `add_supplier()` to also create a
      linked `LedgerAccount` (group "Sundry Debtors" / "Sundry Creditors",
      `account_type='ASSET'` / `'LIABILITY'`) in the SAME transaction
- [ ] Update `create_db.py` to create the 3 new tables and call
      `ensure_system_accounts()`
- [ ] **Test it:** a script runs `ensure_system_accounts()` twice (confirms
      idempotency - no duplicates), adds a customer and a supplier, and
      confirms each now has a linked `ledger_accounts` row with the correct
      group/type

---

## Milestone 11 — Accounting engine: auto-posting for Sales & Purchase (most important)

- [ ] `AccountingService.post_journal_entry(session, date, reference_type,
      reference_id, lines, narration=None, created_by=None) ->
      JournalEntry` — `lines` is a list of `{"account_id":, "debit":,
      "credit":}`. Validates `sum(debit) == sum(credit)` (raise
      `ValueError` if not). Adds rows to the **passed-in session** - does
      NOT open its own session/commit, so it can run inside an existing
      transaction
- [ ] Edit `services/sales_service.py` `create_invoice()` — within the same
      transaction, after computing totals, call `post_journal_entry()` with:
      ```
      Dr <Customer's ledger account>     total
         Cr Sales Account                   taxable_amount
         Cr CGST Output                     cgst   (only if > 0)
         Cr SGST Output                     sgst   (only if > 0)
         Cr IGST Output                     igst   (only if > 0)
      ```
      `reference_type='SALE'`, `reference_id=invoice.id`
- [ ] Edit `services/purchase_service.py` `create_purchase_invoice()` —
      same pattern:
      ```
      Dr Purchase Account                taxable_amount
      Dr CGST Input                      cgst   (only if > 0)
      Dr SGST Input                      sgst   (only if > 0)
      Dr IGST Input                      igst   (only if > 0)
         Cr <Supplier's ledger account>     total
      ```
      `reference_type='PURCHASE'`, `reference_id=invoice.id`
- [ ] **Test it first with a script:** `check_milestone11.py` creates a
      fresh AP customer + sale (`CHK-M11-001`) and a fresh AP supplier +
      purchase (`CHK-M11-002`), then asserts:
      - each journal entry's lines sum to zero (debit total == credit total)
      - the customer's ledger account balance increased by the sale total
      - Sales Account / CGST Output / SGST Output balances increased by the
        expected amounts
      - the supplier's ledger account balance increased (credit side) by the
        purchase total, and Purchase Account / CGST Input / SGST Input moved
        accordingly

---

## Milestone 12 — Day Book & Ledger view

- [ ] `AccountingService.get_day_book(date_from, date_to) -> list[dict]` —
      every journal entry in range with its lines (account name,
      debit/credit), newest first
- [ ] `AccountingService.get_ledger(account_id, date_from=None,
      date_to=None) -> dict` — `{"account_name":, "opening_balance":,
      "entries": [...], "closing_balance":}`, each entry showing date,
      narration, debit, credit, running balance
- [ ] `ui/day_book.py` — `DayBookScreen`: date range pickers + table of
      entries/lines
- [ ] `ui/ledger_view.py` — `LedgerViewScreen`: account picker (all
      `ledger_accounts`) + date range + table with running balance column
- [ ] Add "Accounts" top-level tab in `main.py` containing a nested
      `QTabWidget` with Day Book and Ledger sub-tabs (Trial Balance, P&L,
      Balance Sheet, Outstanding sub-tabs get added in later milestones)
- [ ] **Test it:** using the Milestone 11 fixtures, Day Book shows both
      entries; the Sales Account ledger shows a credit equal to
      `CHK-M11-001`'s taxable amount with the correct running balance; the
      customer's ledger shows the matching debit

---

## Milestone 13 — Trial Balance

- [ ] `AccountingService.get_trial_balance(as_of_date=None) -> list[dict]` —
      one row per account with a non-zero balance:
      `{"account_name":, "account_group":, "debit":, "credit":}` (each
      account's net balance shown on its natural side - Dr balance in the
      debit column, Cr balance in the credit column)
- [ ] `ui/trial_balance.py` — table + totals row (must always show
      total debit == total credit - this is the fundamental double-entry
      check)
- [ ] Add as a sub-tab under "Accounts"
- [ ] **Test it:** `check_milestone13.py` - after the Milestone 11 fixtures,
      assert total debit == total credit, and that Sales Account /
      CGST Output / Purchase Account / CGST Input balances match the
      expected fixture amounts

---

## Milestone 14 — Profit & Loss and Balance Sheet

- [ ] `AccountingService.get_profit_and_loss(date_from, date_to) -> dict` —
      `{"income": [...], "expenses": [...], "net_profit":}` where
      `net_profit = sum(income credit-debit) - sum(expense debit-credit)`
      over the period
- [ ] `AccountingService.get_balance_sheet(as_of_date=None) -> dict` —
      `{"assets": [...], "liabilities": [...], "net_profit_to_date":}`.
      Because debits == credits across the whole ledger by construction,
      `assets == liabilities + net_profit_to_date` automatically - the
      report should show this as a "Profit & Loss A/c (current)" line under
      liabilities for readability, not as a hack to force balance
- [ ] `ui/profit_and_loss.py`, `ui/balance_sheet.py` — date range / as-of
      date pickers + tables. Add both as sub-tabs under "Accounts"
- [ ] **Document the known limitation inline** (code comment + a note in
      `progress.md`): no Trading Account / COGS yet, so "Purchase Account"
      is treated as a period expense regardless of unsold stock. This is a
      timing difference, not a permanent error, and is acceptable for this
      milestone
- [ ] **Test it:** `check_milestone14.py` - using Milestone 11 fixtures,
      `net_profit == CHK-M11-001.taxable_amount - CHK-M11-002.taxable_amount`
      (no other income/expense accounts exist yet), and
      `assets == liabilities + net_profit_to_date` to the cent

---

## Milestone 15 — Customer / Supplier Outstanding

- [ ] `AccountingService.get_outstanding_customers() -> list[dict]` — for
      every customer whose ledger account has a non-zero Dr balance:
      `{"customer_id":, "name":, "gstin":, "outstanding":}`
- [ ] `AccountingService.get_outstanding_suppliers() -> list[dict]` — mirror,
      non-zero Cr balance on the supplier's ledger account
- [ ] `ui/outstanding.py` — two tables (Customers / Suppliers). Add as a
      sub-tab under "Accounts"
- [ ] **Test it:** `check_milestone15.py` - after Milestone 11 fixtures with
      no receipts/payments yet, `CHK-M11-001`'s customer shows outstanding ==
      invoice total, and `CHK-M11-002`'s supplier shows outstanding == invoice
      total

---

## Milestone 16 — Receipts & Payments (banking core)

- [x] `models/bank_account.py` — `BankAccount`: `id`, `name`, `bank_name`,
      `account_no`, `ifsc`, `opening_balance` + audit. Creating one also
      creates a linked `ledger_accounts` row (group "Bank Accounts",
      `account_type='ASSET'`, `bank_account_id` FK set)
- [x] `models/receipt.py` — `Receipt`: `id`, `date`, `customer_id` (FK),
      `payment_mode` (`'CASH' | 'BANK'`), `bank_account_id` (nullable FK,
      required if mode is `'BANK'`), `amount`, `reference_no` (nullable),
      `notes` (nullable) + audit
- [x] `models/payment.py` — `Payment`: mirror of `Receipt` with
      `supplier_id` instead of `customer_id`
- [x] `services/banking_service.py` (new) — `BankingService`:
  - `add_bank_account(...)` — one transaction: `BankAccount` row + linked
    `LedgerAccount`
  - `list_bank_accounts()`
  - `record_receipt(date, customer_id, amount, payment_mode,
    bank_account_id=None, reference_no=None, notes=None, created_by=None)`
    — one transaction: `Receipt` row + journal entry
    `Dr Cash/Bank amount` / `Cr <Customer ledger account> amount`
    (`reference_type='RECEIPT'`)
  - `record_payment(date, supplier_id, amount, payment_mode,
    bank_account_id=None, reference_no=None, notes=None, created_by=None)`
    — `Dr <Supplier ledger account> amount` / `Cr Cash/Bank amount`
    (`reference_type='PAYMENT'`)
  - `list_receipts()`, `list_payments()`
- [x] `ui/banking.py` — sub-tabs: "Bank Accounts" (add/list), "Receipts"
      (record + list, picks customer + amount + mode/bank account),
      "Payments" (mirror for suppliers). Add "Banking" top-level tab
- [x] **Test it:** `check_milestone16.py` - record a receipt for the full
      amount of `CHK-M11-001` -> that customer's outstanding (Milestone 15)
      drops to 0, and the Cash ledger balance increases by the receipt
      amount; record a payment for `CHK-M11-002` -> supplier outstanding
      drops to 0 and Cash decreases accordingly
      *(Done with self-contained `CHK-M16-*` fixtures instead of the
      `CHK-M11-*` ones, so re-running M16 doesn't disturb the M15 check.)*

---

## Milestone 17 — Bank Reconciliation (manual matching, lower priority)

- [x] `models/bank_statement_line.py` — `BankStatementLine`: `id`,
      `bank_account_id` (FK), `date`, `description`, `amount` (signed -
      positive = deposit, negative = withdrawal), `is_matched` (bool,
      default False), `matched_receipt_id` (nullable FK),
      `matched_payment_id` (nullable FK) + audit
- [x] `BankingService.add_statement_line(bank_account_id, date,
      description, amount, created_by=None)` — manual entry only (no file
      import - see Decision 4)
- [x] `BankingService.list_unmatched_statement_lines(bank_account_id)`
      *(plus `list_statement_lines`, `list_unmatched_receipts` /
      `list_unmatched_payments` so the UI can show the candidate side.)*
- [x] `BankingService.match_statement_line(line_id, receipt_id=None,
      payment_id=None)` — sets `is_matched=True` + the relevant
      `matched_*_id` *(validates sign↔kind, same bank account, equal amounts,
      and exactly one of receipt_id/payment_id).*
- [x] `ui/bank_reconciliation.py` — pick a bank account; show unmatched
      statement lines next to unmatched receipts/payments for that account;
      select one of each + "Match" button. Add as a sub-tab under "Banking"
      *(Built as `ReconciliationTab` inside `ui/banking.py` — same file as the
      other Banking sub-tabs — rather than a separate `ui/bank_reconciliation.py`.
      Also has an inline "Add Statement Line" form for the manual entry.)*
- [x] **Test it:** `check_milestone17.py` - add a statement line with the
      same amount/date as the Milestone 16 receipt, match it, confirm
      `is_matched=True` and it no longer appears in the unmatched list
      *(Done with self-contained `CHK-M17-*` fixtures: matches a +deposit line
      to a BANK receipt and a -withdrawal line to a BANK payment, and asserts
      the four validation guards raise.)*

*This milestone was the least critical to day-to-day billing, so it was built
LAST (after the GST returns, Milestones 18-19), per the user's choice.*

---

## Milestone 18 — GST Sales/Purchase Registers + HSN Summary

- [x] `services/gst_report_service.py` (new) — `GstReportService`:
  - `get_sales_register(date_from, date_to) -> list[dict]` — one row per
    `sales_invoice_item` joined with its invoice + item: date, invoice_no,
    customer_name, customer_gstin, hsn_code, taxable_amount, cgst, sgst,
    igst, total
  - `get_purchase_register(date_from, date_to) -> list[dict]` — mirror for
    purchases
  - `get_hsn_summary(date_from, date_to, direction='SALES' | 'PURCHASE')
    -> list[dict]` — grouped by `(hsn_code, gst_rate)`: total quantity,
    total taxable, total cgst/sgst/igst
- [x] `ui/gst_reports.py` — date range pickers; sub-views (or a combo) for
      Sales Register / Purchase Register / HSN Summary; "Export to Excel"
      button using OpenPyXL (already a dependency, currently unused - see
      `Instructions_Claude.txt` Module 14 "Export Formats: Excel, PDF")
- [x] Add "GST" top-level tab containing this as the "Registers/HSN"
      sub-tab
- [x] **Test it:** `check_milestone18.py` - using Milestone 11 fixtures
      (and existing real invoices, since this reads raw invoice data and
      doesn't depend on the accounting engine), assert register rows match
      invoice data and HSN summary totals equal the sum of fixture line
      amounts/taxes for that HSN code
      *(Done with self-contained `CHK-M18-*` fixtures on a sentinel date in
      FY 2019-20, so the date-filtered reports see only the fixtures and not
      real dev-DB invoices. Covers intra-state CGST/SGST, B2C, and
      inter-state IGST lines.)*

---

## Milestone 19 — GSTR-1 / GSTR-3B Summary

- [x] `GstReportService.get_gstr1_summary(date_from, date_to) -> dict`:
  - `"b2b"` — list of `{gstin, invoice_no, date, taxable_value, cgst, sgst,
    igst}` for customers with a GSTIN
  - `"b2c_small"` — aggregated `{taxable_value, cgst, sgst, igst}` for
    customers without a GSTIN
  - `"hsn_summary"` — reuse `get_hsn_summary(direction='SALES')`
- [x] `GstReportService.get_gstr3b_summary(date_from, date_to) -> dict`:
  - `"outward_taxable_supplies"` — total taxable_amount, cgst, sgst, igst
    from sales in range (GSTR-3B table 3.1(a))
  - `"itc_available"` — total cgst, sgst, igst from purchases in range
    (table 4)
  - `"net_tax_payable"` — output GST minus ITC per tax head, floored at 0;
    a negative value is reported separately as `"itc_carried_forward"`
- [x] `ui/gst_returns.py` — date range picker, read-only summary tables for
      GSTR-1 and GSTR-3B ("figures to enter on the GST portal" - no
      e-filing integration). Add as the "Returns" sub-tab under "GST"
- [x] **Test it:** `check_milestone19.py` - using Milestones 11/18 fixtures,
      manually compute expected net tax payable per tax head and assert it
      matches `get_gstr3b_summary()`
      *(Reuses `check_milestone18.build_fixtures()`; asserts net payable
      cgst 5 / sgst 5 / igst 90 from outward 95/95/90 minus ITC 90/90/0.)*

---

## Phase 2 Part 2 is DONE when:

Every sale and purchase posts itself to the books automatically, you can see
a Trial Balance that balances to the paisa, a P&L and Balance Sheet for any
period, who owes you money and who you owe, record receipts/payments against
those balances, optionally reconcile them against a bank statement, and pull
the GST register/HSN/GSTR-1/GSTR-3B numbers needed to file returns.

After this, Phase 2 (per `ROADMAP.md`) is complete and Phase 3 (OCR,
Document Management, AI Reporting) would be next - plan that separately when
the time comes.
