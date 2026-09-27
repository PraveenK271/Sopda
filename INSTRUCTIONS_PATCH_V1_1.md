# INSTRUCTIONS_PATCH_V1_1.md — Gemini ERP Patch v1.1.0

Instructions for Claude Code. Read `CLAUDE.md` and `PROJECT_MEMORY.md` before
starting anything in this file.

**What this patch delivers**

1. Discount and Special Discount on purchases, included in price calculation
2. Edit an existing sales invoice, with stock, ledgers and reports staying correct
3. Credit Notes received from suppliers, reducing the supplier's balance

**Non-negotiable requirement:** this ships as a **patch to an existing
installation**. Users already have live data in their `GeminiERP` database.
Nothing in this patch may destroy, alter or orphan a single existing row.

Build order is P1 → P2 → P3 → P4 → P5. P1 is the foundation the rest relies
on. Same discipline as always: **build → test → confirm → next.**

---

## Ground rules for this patch

The existing golden rules from `CLAUDE.md` all still apply — stock is
calculated not stored, one transaction = all or nothing, no business logic in
the UI. On top of those, three rules specific to patching a live database:

**Rule A — Migrations are ADDITIVE ONLY.**
You may ADD a column (nullable, or NOT NULL with a default) and ADD a table.
You may **never** drop a column, rename a column, change a column's type, or
delete a row as part of a migration. Additive-only means an old database
upgrades safely, and rollback is just restoring a backup.

*Why this matters:* `Base.metadata.create_all()` creates missing **tables**
but does **not** add missing **columns** to tables that already exist. On an
existing user database, adding `discount_percent` to the model without a
migration produces `Invalid column name 'discount_percent'` at runtime. This
is the single most likely way this patch breaks someone's live system.

**Rule B — Existing records must behave exactly as before.**
Every new field gets a default that makes old rows compute to the same
numbers they do today. A purchase invoice created last month must still show
the same total after the patch. Add a test that proves this.

**Rule C — Back up before migrating, automatically.**
The app backs up the database before running any pending migration, without
asking. If the backup fails, the migration does not run.

---

## P1 — Migration framework (build this first)

### Why hand-rolled instead of Alembic

Alembic is the standard tool and it is genuinely good, but it brings
autogenerate (which produces migrations you must review carefully), its own
CLI, and awkward SQLite behaviour for anything beyond ADD COLUMN. For this
project a ~150-line runner is enough, adds no dependency, works identically
on SQLite and SQL Server, and you can read every line of it. Revisit Alembic
if migrations ever become complex — with an additive-only rule, they should
not.

### Build

- [ ] `models/schema_migration.py` — `SchemaMigration`:
      `id`, `version` (String(20), unique), `description` (String(255)),
      `applied_date` (DateTime), `applied_by` (String(50)) + audit columns.

- [ ] `migrations/` package at the project root, containing numbered modules:
      `m001_purchase_discounts.py`, `m002_sales_invoice_audit.py`,
      `m003_supplier_credit_notes.py`.
      Each exposes:
      ```python
      VERSION = "001"
      DESCRIPTION = "Add discount fields to purchase invoices"

      def upgrade(connection, dialect_name):
          ...
      ```

- [ ] `services/migration_service.py` — `MigrationService`:
  - `get_applied_versions(session) -> set[str]`
  - `get_pending_migrations(session) -> list[module]` — sorted by VERSION
  - `run_pending(session, applied_by) -> list[str]`
      Runs each pending migration **in its own transaction**, records it in
      `schema_migrations` on success, and stops on the first failure with a
      clear message naming the version. Does not continue past a failure.
  - `column_exists(connection, table_name, column_name) -> bool`
      Backend-neutral, using SQLAlchemy's inspector:
      ```python
      from sqlalchemy import inspect
      cols = [c["name"] for c in inspect(connection).get_columns(table_name)]
      return column_name in cols
      ```
  - `table_exists(connection, table_name) -> bool` — same approach.
  - `add_column(connection, dialect_name, table, column_def_sqlite,
     column_def_mssql)` — helper handling the dialect difference:
      SQLite uses `ALTER TABLE x ADD COLUMN y ...`,
      SQL Server uses `ALTER TABLE x ADD y ...` (no `COLUMN` keyword).

- [ ] **Every migration must be idempotent.** Check `column_exists` /
      `table_exists` before acting. Running the patch twice must be harmless.

- [ ] `services/backup_service.py` — add
      `auto_backup_before_migration(reason) -> str | None`:
      - SQLite: copy the `.db` file to
        `backups/pre_patch_<version>_<timestamp>.db`
      - SQL Server: execute
        `BACKUP DATABASE GeminiERP TO DISK = '<path>'` and return the path
      - Returns the backup path, or raises if it could not be written.

- [ ] Wire into `main.py` startup, in this exact order:
      1. `ensure_roles_and_admin()` (existing)
      2. Check for pending migrations
      3. If any: show a modal "Updating database, please wait" dialog →
         `auto_backup_before_migration()` → `run_pending()` → show which
         versions were applied and where the backup was written
      4. If a migration fails: show the error, name the backup file, and
         **exit** rather than opening a half-migrated app
      5. Login dialog (existing)

- [ ] Add `migrations/` to the PyInstaller `.spec` `datas` list, and add
      `migrations.m001_purchase_discounts` etc. to `hiddenimports` — the
      modules are loaded dynamically, so PyInstaller will not find them by
      static analysis. (Same class of problem as the `passlib` dynamic-import
      issue already recorded in `PROJECT_MEMORY.md`.)

- [ ] **Test it:** `check_p1.py`
      - on a fresh database, all migrations apply and are recorded
      - running `run_pending()` a second time applies nothing and errors nothing
      - `column_exists` returns correctly for a known and an unknown column
      - a deliberately failing migration is not recorded in
        `schema_migrations`, and the run stops there

---

## P2 — Discount and Special Discount on purchases

### The design, and the one thing that is easy to get wrong

Two levels of discount:

- **Line discount** — a percentage off a single line, the normal trade
  discount a supplier gives per item.
- **Special discount** — a flat rupee amount off the whole bill, the
  "and I'll knock ₹500 off" at the bottom of the invoice.

A discount shown on the invoice at the time of supply reduces the **taxable
value** for GST. So both discounts must be applied **before** GST is
calculated, not after.

**The trap:** a bill-level special discount cannot simply be subtracted from
the invoice total, because different lines may carry different GST rates. It
must be **apportioned across the lines in proportion to each line's taxable
value**, and GST recomputed per line. Subtracting it at the end silently
produces the wrong CGST/SGST split.

### Calculation order (implement exactly this)

```
For each line:
    line_gross      = quantity × rate
    line_discount   = line_gross × discount_percent / 100
    line_net        = line_gross − line_discount

invoice_net = sum(line_net for all lines)

For each line:
    share           = line_net / invoice_net          (0 if invoice_net is 0)
    apportioned     = round(special_discount × share, 2)
    line_taxable    = line_net − apportioned
    line_gst        = round(line_taxable × gst_rate / 100, 2)
```

**Rounding rule:** apportioning by percentage will not sum back to the
special discount exactly. Give the **last line the remainder**, so
`sum(apportioned) == special_discount` to the paisa. Assert this in the test.

**Guard rails:**
- `discount_percent` must be 0–100. Reject outside that range.
- `special_discount` may not exceed `invoice_net`. Reject with a clear message.
- Blank, `None` or empty string → treat as **0**. Never raise an error for a
  missing discount. This was an explicit requirement.

### Build

- [ ] Migration `m001_purchase_discounts.py`, additive:
      - `purchase_invoice_items`: add `discount_percent` NUMERIC(5,2)
        DEFAULT 0, `discount_amount` NUMERIC(15,2) DEFAULT 0
      - `purchase_invoices`: add `special_discount` NUMERIC(15,2) DEFAULT 0,
        `total_discount` NUMERIC(15,2) DEFAULT 0 (line discounts + special,
        stored for reporting)
      All default 0 → existing bills compute identically to today.

- [ ] Update `models/purchase_invoice.py` and
      `models/purchase_invoice_item.py` to match. Use explicit precision —
      `Numeric(15, 2)` — never bare `Numeric()`, which fails on SQL Server.

- [ ] Update `PurchaseService.create_purchase_invoice()` to accept the new
      optional fields and apply the calculation above. The accounting journal
      posts the **net** taxable value and the **net** input GST:
      ```
      Dr Purchase              (net taxable after all discounts)
      Dr Input CGST/SGST/IGST  (on the net taxable)
         Cr Supplier               (net total)
      ```
      On-invoice discounts are part of the purchase price — do **not** post
      them to a separate discount ledger. (Post-supply discounts received
      later via credit note are different; that is P4.)

- [ ] Update the purchase entry screen: a `Discount %` column on each line
      (optional, blank = 0), a `Special Discount` field near the totals, and
      a live totals panel showing Gross → Discount → Taxable → GST → Net.

- [ ] Update the purchase PDF/print layout to show the discount columns and
      the special discount line, but **only when non-zero** — a bill with no
      discount should look exactly as it does today.

- [ ] Purchase Register and supplier reports show the net (post-discount)
      figures.

- [ ] **Sales-side discounts are deliberately out of scope for this patch.**
      The same pattern will apply when added. Record this in `progress.md`.

- [ ] **Test it:** `check_p2.py`
      - a bill with no discount fields at all saves and totals exactly as
        before the patch (Rule B)
      - 10 units @ ₹100 with 10% line discount → taxable 900, GST on 900
      - two lines at different GST rates with a bill-level special discount:
        the apportioned amounts sum exactly to the special discount, and
        each line's GST is computed on its own post-apportionment taxable
      - `discount_percent = 150` is rejected
      - `special_discount` greater than the net value is rejected
      - blank/None discount is accepted and treated as 0, no error raised
      - the journal entry balances and its Input GST equals the net GST

---

## P3 — Edit an existing sales invoice

### Why this is the riskiest feature in the patch

An invoice is not just a row. It is a row, a set of lines, a set of stock
movements and a balanced journal entry. Editing it means undoing all four
consistently, and any partial undo leaves stock or the books permanently
wrong — exactly the failure this whole project exists to prevent.

### The approach: reverse, then re-post. Never delete.

When an invoice is edited, the original stock movements and journal entries
**stay in the database**, and reversing entries are posted against them,
followed by the new entries.

Three reasons this is better than deleting and recreating:
- Accounting convention is absolute here — a posted journal is reversed,
  never deleted. Any auditor expects to see the trail.
- `get_current_stock()` needs **zero changes**: an OUT of 10 followed by a
  reversal IN of 10 and a new OUT of 8 nets to 8 automatically.
- The stock ledger honestly shows that an edit happened, rather than hiding
  it behind a soft-deleted row.

### Build

### Why "reverse everything, then re-post" handles line removal for free

Worth understanding before you build it, because it is the reason not to
"optimise" this later into a diff of old lines vs new lines.

Invoice has Item A × 10 and Item B × 5. Stock: A 100 → 90, B 50 → 45.
The user removes Item B entirely.

- Step 4 reverses **all active** OUT rows → IN 10 for A, IN 5 for B
  (stock back to A 100, B 50)
- Step 7 writes OUT rows for the **new line set only** → OUT 10 for A,
  nothing for B
- Result: A = 90, B = 50 — both correct

There is no "removed line" code path anywhere, because removal is just a
line that does not appear in the new set. A diff-based implementation would
need to detect removals explicitly and would likely miss them. Do not
replace this with a diff.

### Build

- [ ] Migration `m002_sales_invoice_audit.py`, additive:
      - new table `sales_invoice_audit`: `id`, `invoice_id` (FK),
        `edited_by` (String(50)), `edited_date` (DateTime),
        `reason` (String(500), **required**), `before_snapshot` (Text, JSON),
        `after_snapshot` (Text, JSON) + audit columns
      - `sales_invoices`: add `edit_count` INTEGER DEFAULT 0,
        `last_edited_date` DATETIME NULL
      - `stock_transactions`: add `is_reversed` BOOLEAN DEFAULT 0 (False)
      - `journal_entries`: add `is_reversed` BOOLEAN DEFAULT 0 (False)

      **The two `is_reversed` columns are what make a SECOND edit safe.**
      Without them, editing the same invoice twice reverses rows that were
      already reversed on the first edit, and stock silently goes wrong.
      See "The second-edit trap" below — this is the most dangerous bug in
      the whole patch, and the flags are the fix.

- [ ] Add two `reference_type` values wherever that constant list lives:
      `'SALE_EDIT_REVERSAL'` for both the reversing stock rows and the
      reversing journal entry.

- [ ] `SalesService.update_invoice(session, invoice_id, new_data, reason,
      modified_by)` — the whole thing inside **one** database transaction:
      1. Load the invoice and its active lines
      2. Run the permission and lock checks below; abort before any write
      3. Capture `before_snapshot` as JSON
      4. For each OUT stock row of this invoice **where `is_reversed` is
         False**, write a reversing **IN** of the same quantity,
         `reference_type='SALE_EDIT_REVERSAL'`, `reference_id=invoice_id`,
         then set `is_reversed = True` on the row just reversed.
         Iterate **per stock-transaction row, never grouped by item** — the
         same item can legitimately appear on two lines of one invoice
         (different rates), and grouping would under-reverse it.
         Date the reversing rows the **same as the original invoice date**,
         not today, so the stock ledger reads correctly by period.
      5. Post a reversing journal entry for each journal entry of this
         invoice **where `is_reversed` is False** (debits and credits
         swapped), `reference_type='SALE_EDIT_REVERSAL'`, dated the
         **original invoice date**, via the existing
         `AccountingService.post_journal_entry()` — it already refuses to
         save anything unbalanced, so do not bypass it. Then set
         `is_reversed = True` on the entry just reversed.
      6. Soft-delete the old `sales_invoice_items` rows (`is_deleted=True`)
      7. Write the new lines, new OUT stock rows, and a new balanced journal
         entry using the existing GST logic — same state-based CGST/SGST vs
         IGST rules, no duplicated calculation
      8. Update the header totals, increment `edit_count`, set
         `last_edited_date`
      9. Write the `sales_invoice_audit` row with both snapshots
      10. Commit

- [ ] **Checks that must run before any write:**
      - `invoice_no` **cannot be changed**. It is the legal document number.
        Lock the field in the UI and reject a changed value in the service.
      - **At least one line is required.** Removing every line is rejected
        with: "An invoice must have at least one item. To cancel this
        invoice, issue a credit note." An invoice number with zero lines and
        a zero total is not a valid document, and silently allowing it would
        create one. (Invoice cancellation is **not** in this patch — see
        "Out of scope" below.)
      - **Stock availability is checked against the NEW lines**, after the
        reversal has notionally returned the old quantities. So editing
        10 → 15 is checked against stock that already includes the 10 coming
        back. Apply whatever oversell policy the app already uses on a normal
        sale — do not silently bypass it just because this is an edit, and do
        not double-count the returning stock.
      - If the invoice date falls in a period locked by `period_locks`
        (Historical Import H6), **block** the edit with a clear message.
      - If the invoice date is in a month earlier than the current month,
        **warn** the user before proceeding: once a GST return for that
        period has been filed, the legally correct fix is a credit note or
        debit note, not an edit. Warn, do not block — the software cannot
        know what has actually been filed.
      - **Changing the invoice date** is allowed only within the same month
        as the original. Moving a sale into a different month shifts it
        between GST return periods; reject that with a message pointing at
        the credit-note route.
      - **Changing the customer** is allowed, but warn clearly first: the
        customer is a core field of the tax invoice, and a different buyer is
        arguably a different document. The accounting handles it correctly
        (the reversal credits the original customer, the new entry debits the
        new one) and GST recalculates from the new customer's state, so
        CGST+SGST can legitimately become IGST. Warn, then proceed.
      - If any **receipt** has been recorded against this invoice, warn
        before proceeding: reducing the invoice below what has been received
        leaves the customer with a credit balance. Warn, do not block — an
        advance or overpayment is a real situation.
      - `reason` is mandatory and non-empty.
      - Permission: Administrator and Accountant only. A Sales User must not
        see the Edit button. Enforce in the service, not only the UI.

### The second-edit trap (read before writing step 4)

The single most dangerous bug available in this feature. Editing the **same
invoice twice** is where a naive implementation corrupts stock silently.

Stock starts at 100. Invoice sells 10.

```
Edit 1:  OUT 10  →  reversing IN 10  →  new OUT 8        stock = 92  ✓
Edit 2:  the invoice now has THREE stock rows: OUT 10, IN 10, OUT 8
```

If step 4 reverses "every OUT row of this invoice", it reverses **OUT 10 and
OUT 8** — 18 units returned instead of 8 — and the stock ends up 10 too high.
Nothing errors. The Trial Balance still balances. The number is just wrong,
and it stays wrong.

The `is_reversed` flag is the fix: on edit 2 only the OUT 8 has
`is_reversed = False`, so only it is reversed. Same reasoning for journal
entries — reverse only entries not already reversed, or the books double up.

`get_current_stock()` needs **no change** for any of this: it sums every row
regardless of flags, and the flag exists only to stop a row being reversed
twice.

Two further notes on the stock rows this produces:

- A **rate-only change** (quantity unchanged) writes a reversing IN 10 and a
  new OUT 10 — no net stock movement, two extra ledger rows. That is
  acceptable noise. Do **not** optimise it away by skipping unchanged lines;
  that reintroduces the diff logic this design exists to avoid.
- An item **soft-deleted from the item master** after the original sale must
  still accept its reversing IN row. Only the *new* lines are validated
  against active items.

- [ ] UI: an "Edit" button on the sales log / invoice view that opens the
      billing screen pre-filled, with `invoice_no` read-only and a mandatory
      "Reason for edit" box. On save, regenerate the PDF.

- [ ] An "Edit History" view on the invoice showing every audit row —
      who, when, why.

### Test it: `check_p3.py`

**Stock scenario matrix.** Every row is a separate assertion. Set up Item A
with stock 100 and Item B with stock 50 before each.

| # | Original invoice | Edited to | Expected stock A | Expected stock B |
|---|---|---|---|---|
| 1 | A × 10 | A × 8 (reduce) | 92 | — |
| 2 | A × 10 | A × 15 (increase) | 85 | — |
| 3 | A × 10, B × 5 | A × 10 (**B line removed**) | 90 | **50** |
| 4 | A × 10 | A × 10, B × 5 (line added) | 90 | 45 |
| 5 | A × 10 | B × 10 (item swapped) | **100** | 40 |
| 6 | A × 5, A × 3 (same item, two lines) | A × 5 (one line dropped) | 95 | — |
| 7 | A × 10 @ ₹100 | A × 10 @ ₹120 (rate only) | 90 | — |
| 8 | A × 10 → edit to 8 → **edit again to 6** | — | **94** | — |

Row 3 is the removal case. Row 6 catches an implementation that groups the
reversal by item instead of per stock row. **Row 8 is the second-edit trap —
if it reads 84 or 104 instead of 94, `is_reversed` is not being honoured.**

**Accounting assertions**
- after each edit, the invoice's journal entries **net** to the new amounts,
  and the Trial Balance total debit still equals total credit
- the original stock rows and original journal entry **still exist** —
  nothing was hard-deleted
- reversing rows and reversing journal entries carry the **original invoice
  date**, not today's date, so the period P&L is right
- customer changed from an Andhra Pradesh buyer to an out-of-state buyer:
  the original customer's ledger is credited back to zero, the new customer
  is debited, and the tax switches from CGST+SGST to **IGST**

**Guard assertions (each must raise)**
- removing every line ("invoice must have at least one item")
- editing an invoice whose date is in a locked period
- changing `invoice_no`
- moving the invoice date into a different month
- an empty `reason`
- a Sales User calling `update_invoice()`
- increasing quantity beyond available stock, if the app's oversell policy
  blocks it on a normal sale — same behaviour here, no bypass

**Warning assertions (must warn, must NOT block)**
- editing an invoice dated in an earlier month
- editing an invoice that already has a receipt recorded against it
- changing the customer

**Audit and rollback**
- `sales_invoice_audit` gains one row per edit, both snapshots populated,
  `edit_count` on the invoice matches the number of audit rows
- **the rollback test, and the most important one here:** force a failure
  part-way through (an invalid item on the new lines) and confirm stock,
  the journal entries and the invoice are **byte-for-byte** as they were
  before — no orphan reversing rows, no flipped `is_reversed` flags, no
  bumped `edit_count`

### Out of scope for P3 (record in `progress.md`)

- **Cancelling an invoice.** Editing cannot empty an invoice, and there is no
  cancel/void flow in this patch. The correct instrument is a credit note to
  the customer — which is the sales-side counterpart of P4 and is not built
  here. If a user needs to void a sale today, the honest answer is a credit
  note once that exists; until then, note it and move on.
- **Editing purchase invoices.** The same reverse-and-re-post pattern applies
  and should reuse this design when added.
- **Moving an invoice between months**, and any edit to an invoice whose GST
  return has been filed. Blocked or warned here; the credit-note route is the
  real fix.

---

## P4 — Credit Notes received from suppliers

### Background: what the law actually requires

You asked me to check this properly, and it matters — the rules changed in
late 2025 and again in 2026, and the two kinds of credit note behave very
differently in your books.

**There are two distinct documents, and the software must not blur them.**

**1. GST credit note (Section 34, CGST Act).** Reduces the taxable value
*and* the tax on the original supply. It carries GST. As the recipient, you
must reverse the proportionate input tax credit. Since 1 October 2025 the
supplier can only reduce their own output tax if you have actually reversed
that ITC — which is why suppliers now chase you about it. These credit notes
appear on your Invoice Management System (IMS) dashboard, and from the
October 2025 tax period accepting one requires a declaration of how much ITC
you are reversing. Accept it and the reduction flows into your GSTR-2B;
reject it and the supplier's liability reopens.

**2. Commercial (or financial) credit note.** Carries no GST. Circular
251/08/2025-GST dated 12 September 2025 settled the treatment: because it
does not reduce the original transaction value, the supplier's tax liability
is unchanged and **you are not required to reverse any ITC** on the discount
passed through it. Suppliers use this route when the Section 34 window has
closed or the discount does not satisfy Section 15(3)(b).

So: **a GST credit note touches your Input GST; a commercial credit note does
not.** Recording one as the other misstates your ITC — under-reverse and you
are holding credit you are not entitled to; over-reverse and you lose credit
you were entitled to. The type field is therefore mandatory, with no default.

There is also a time limit — credit notes must be declared by 30 November
following the end of the financial year, or the filing of the annual return,
whichever is earlier — so the register below should make stale notes visible.

*Sources are listed at the end of this file. Treat the above as the mechanics
to build, and have the accountant confirm the filing treatment for specific
cases — this is not tax advice.*

### Scope decision: discounts only, not goods returns

These are credit notes given by suppliers **as discounts**, so this feature
does **not** touch stock. A credit note for physically returned goods must
also reduce stock, and that belongs in **Purchase Return** (already in
`Instructions_Claude.txt`, Module 7) — a separate feature.

Enforce it: `reason` includes a `GOODS_RETURN` option, and selecting it
blocks the save with "Use Purchase Return for goods physically sent back —
this screen does not adjust stock." Better a clear refusal than silently
wrong inventory.

### Build

- [ ] Migration `m003_supplier_credit_notes.py`, additive:
      new table `supplier_credit_notes`:

      | Column | Type | Notes |
      |---|---|---|
      | `id` | Integer PK | |
      | `credit_note_no` | String(50) | the supplier's number |
      | `credit_note_date` | DateTime | |
      | `supplier_id` | Integer FK | required |
      | `linked_purchase_invoice_id` | Integer FK, **nullable** | many notes are not invoice-specific |
      | `note_type` | String(20) | `'GST'` or `'COMMERCIAL'` — **mandatory, no default** |
      | `reason` | String(50) | `DISCOUNT` / `RATE_DIFFERENCE` / `QUALITY_CLAIM` / `SCHEME` / `GOODS_RETURN` |
      | `taxable_value` | Numeric(15,2) | GST type only |
      | `cgst` / `sgst` / `igst` | Numeric(15,2) | GST type only |
      | `total_amount` | Numeric(15,2) | |
      | `itc_reversed` | Boolean, default False | GST type only |
      | `itc_reversal_amount` | Numeric(15,2), default 0 | |
      | `ims_status` | String(20), default `'PENDING'` | `PENDING` / `ACCEPTED` / `REJECTED` |
      | `notes` | String(500), nullable | |
      | + audit columns | | |

      Uniqueness is **per supplier**: the same `credit_note_no` from two
      different suppliers is legitimate.

- [ ] Add a `DISCOUNT_RECEIVED` system ledger account (type `INCOME`) to
      `services/chart_of_accounts.py` and seed it in
      `ensure_system_accounts()` — idempotent, like the existing accounts.

- [ ] `services/credit_note_service.py` — `CreditNoteService`:
  - `create_credit_note(session, data, created_by) -> SupplierCreditNote`
    One transaction: write the note, post the journal entry, done.
  - `list_credit_notes(session, supplier_id=None, from_date=None, to_date=None)`
  - `update_ims_status(session, credit_note_id, status, itc_reversed,
     itc_reversal_amount, modified_by)`

  **Journal entries — the two types differ, and this is the whole point:**

  GST credit note:
  ```
  Dr Supplier                    total_amount
     Cr Discount Received              taxable_value
     Cr Input CGST                     cgst
     Cr Input SGST                     sgst
     Cr Input IGST                     igst
  ```

  Commercial credit note:
  ```
  Dr Supplier                    total_amount
     Cr Discount Received              total_amount
  ```
  No GST ledger is touched at all.

  Post both through the existing `AccountingService.post_journal_entry()`.
  Use `reference_type='SUPPLIER_CREDIT_NOTE'`.

- [ ] Validation:
      - `note_type` is mandatory — no default, no guessing
      - GST type: `taxable_value + cgst + sgst + igst` must equal
        `total_amount` within ₹1; reject otherwise
      - GST type must follow the same state rule as everywhere else —
        CGST+SGST for an in-state supplier, IGST for out-of-state.
        Reject a note carrying both
      - Commercial type: the GST fields must be zero or empty
      - If `linked_purchase_invoice_id` is given, warn (do not block) when
        `total_amount` exceeds that invoice's total
      - `reason = GOODS_RETURN` → blocked, with the message above

- [ ] UI `ui/credit_notes.py` under the Purchases tab:
      entry form with a prominent **type selector** at the top that shows a
      one-line plain-English explanation of each option and switches the GST
      fields on/off; a list view of recorded notes with `ims_status`; and an
      "Update IMS status" action for reconciling against GSTR-2B.

- [ ] Reports:
      - **Credit Notes Received Register** — date, supplier, number, type,
        taxable, GST, total, IMS status. Excel and PDF, for reconciling
        against GSTR-2B
      - Supplier Outstanding and the Supplier Ledger must include credit
        notes as reductions (they will automatically, via the journal, but
        test it explicitly)
      - A filter or flag for notes still `PENDING` in IMS, and for notes
        approaching the 30 November declaration cut-off

- [ ] **Test it:** `check_p4.py`
      - a GST credit note of ₹1,180 (₹1,000 + 9% + 9%) reduces the supplier
        balance by 1,180, credits Discount Received 1,000, and credits Input
        CGST and Input SGST 90 each
      - a commercial credit note of ₹1,180 reduces the supplier balance by
        1,180, credits Discount Received 1,180, and leaves **every GST
        ledger untouched**
      - both journal entries balance; the Trial Balance still balances
      - a GST note whose components do not sum to the total is rejected
      - a GST note carrying both SGST and IGST is rejected
      - `note_type` omitted is rejected
      - `reason = GOODS_RETURN` is rejected with the purchase-return message
      - supplier outstanding drops by the credit note total
      - the same `credit_note_no` under two different suppliers is accepted

---

## P5 — Documentation, packaging and release

### Documentation updates

- [ ] `CLAUDE.md` — add a **Patching rules** section carrying Rules A, B and
      C from the top of this file, and note that every schema change from now
      on needs a numbered migration.
- [ ] `ROADMAP.md` — add a "Maintenance patches" section and record v1.1.0
      with its three features. Note that sales-side discounts and Purchase
      Return remain open.
- [ ] `PROJECT_MEMORY.md` — update section 7 (build status), add the new
      decisions to section 8 (reverse-don't-delete for edits; the two credit
      note types), and add to section 6's gotcha table: *"`create_all()` does
      not add columns to existing tables — schema changes need a migration."*
- [ ] `progress.md` — add v1.1.0 with what shipped and the known limitations
      (sales discounts not included; no invoice cancellation / void flow and
      no sales-side credit note; purchase invoices are not editable;
      goods-return credit notes deferred to Purchase Return; IMS status is
      manually maintained, not fetched from the portal).
- [ ] `CHECKLIST_PATCH_V1_1.md` — the tickable version of P1–P5, matching the
      format of the existing checklists.
- [ ] `DISTRIBUTION_README.md` — an "Updating from an earlier version"
      section: install over the existing folder, keep `gemini_erp.db` / the
      `.env` file, and expect a one-time "Updating database" message on first
      launch. Tell users where the automatic backup is written.

### Build and release

- [ ] Add `APP_VERSION = "1.1.0"` in one place (a `version.py`), shown in the
      main window title bar and on the About/Settings screen.
- [ ] `.spec` file: include `migrations/` in `datas`, add each migration
      module to `hiddenimports`.
- [ ] Build with `build.bat`, then test the **upgrade path**, which is the
      part that actually matters:
      1. Take a copy of a **pre-patch** database containing real invoices,
         purchases and journal entries
      2. Point the new build at that copy
      3. Launch it. Confirm: the backup is written, migrations apply, the
         app opens
      4. Open a purchase invoice created **before** the patch — its total
         must be **unchanged**
      5. Confirm the Trial Balance total is identical to its pre-patch value
      6. Now use the three new features on that same database
- [ ] Also test a **fresh install** (empty database) — migrations must apply
      cleanly on a database created by `create_all()` too.

### Rollback plan

Because migrations are additive-only, rollback is simple, and it should be
written down for users rather than improvised:

1. Close the application
2. Restore the automatic pre-patch backup from `backups/`
3. Reinstall the previous version folder

Document this in `DISTRIBUTION_README.md`. Never write a "downgrade"
migration — restoring a backup is safer and easier to reason about.

---

## Patch v1.1.0 is DONE when

A user with existing live data installs the new folder over their old one,
launches it, sees a one-time database update, and finds every pre-existing
invoice, stock figure and ledger balance exactly as they left it — and can
then record a discounted purchase, correct a sales invoice, and enter a
supplier credit note, with the books balanced after each.

---

## Sources on credit note treatment (for the accountant)

- Section 34, CGST Act 2017 — credit and debit notes, the 30 November
  declaration deadline, GSTR-1 Table 9B reporting
- Section 34(2) proviso as substituted by the Finance Act 2025 (s.126),
  effective 1 October 2025 — the supplier's output tax reduction now depends
  on the recipient reversing the corresponding ITC
- Section 15(3)(b), as amended — post-supply discounts via credit note with
  ITC reversal; the prior-agreement condition dropped
- Circular 251/08/2025-GST dated 12 September 2025 — commercial/financial
  credit notes do not reduce transaction value, so no ITC reversal is
  required of the recipient
- Circular 212/6/2024-GST — documentary proof of ITC reversal; CA/CMA
  certificate where the tax involved exceeds ₹5,00,000, self-declaration below
- IMS credit note handling from the October 2025 tax period — accept/reject
  and the ITC reversal declaration
