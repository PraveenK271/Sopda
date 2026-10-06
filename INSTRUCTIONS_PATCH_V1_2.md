# INSTRUCTIONS_PATCH_V1_2.md — Gemini ERP Patch v1.2.0

Instructions for Claude Code. Read `CLAUDE.md`, `PROJECT_MEMORY.md` and
`INSTRUCTIONS_PATCH_V1_1.md` (for the migration framework and the
reverse-don't-delete pattern) before starting anything here.

**What this patch delivers**

1. **Cancel a sales invoice** — rolls all its stock back into inventory and
   reverses its accounting, while keeping the invoice number in the sequence
2. **Correct a wrong invoice number** — the actual fix for a mistyped number,
   without creating a phantom cancelled invoice
3. **A "GST filed up to" date** in Settings, so the guards on both of the
   above can genuinely be enforced instead of merely advised

Prerequisite: **v1.1.0 must be installed first.** This patch reuses the
migration runner from P1 and the `is_reversed` flags from m002. Migration
numbering continues at **m004**.

Build order D1 → D2 → D3 → D4. Same discipline: **build → test → confirm →
next.**

---

## Read this before building: it is "cancel", not "delete"

The feature asked for was "delete the invoice". Building it as a true delete
would create a problem in a GST audit, so this patch builds it as a
**cancellation** instead. The difference matters, and here is why in plain
terms.

Rule 46(b) of the CGST Rules requires tax invoice numbers to be a
**consecutive serial number**, unique within the financial year. Cancelled
invoices stay part of that sequence — cancelling an invoice does **not**
create a gap in the numbering, and in GSTR-1 cancelled invoices are listed
and separately identified rather than erased. An invoice row that simply
vanishes leaves a hole between 104 and 106, and the first question in an audit
is what happened to 105.

There is also a timing rule. Before the return is filed, cancelling an
invoice is fine. **Once GSTR-1 for that period has been filed, you cannot
cancel the invoice at all** — the correct instrument is a credit note in the
next return, which keeps the audit trail intact.

So the design is:

- **Never hard-delete.** The invoice row, its line items and its original
  stock and journal rows all stay. The invoice is marked `CANCELLED`.
- **The number stays consumed.** Cancelling invoice 105 does not free up 105
  for reuse. No gaps, no reuse.
- **Stock and books self-correct** through reversing entries, exactly as the
  P3 edit does.
- **Filed periods are blocked**, with a message pointing at the credit-note
  route.

### And for the problem that prompted this

The stated reason was a mistyped invoice number, with edit refusing to change
it. Cancelling and re-entering *works*, but it leaves a cancelled invoice in
the system under a number that never existed in the physical bill book — an
oddity an auditor would ask about.

So **D2 builds a guarded invoice-number correction** as well. For a mistyped
number on an unfiled invoice, correcting the number is the cleaner fix: no
phantom cancelled document, no stock movement at all, just a corrected label
and an audit trail. Cancellation then stays for what it is actually for —
a sale that genuinely did not happen.

Both are built. Use number-correction for typos, cancellation for voided
sales.

*This is the mechanics to build, not tax advice. Have the accountant confirm
the treatment for specific cases. Sources at the end of this file.*

---

## D1 — Cancel a sales invoice

### Migration m004

- [ ] `migrations/m004_invoice_cancellation.py`, additive only
      (same rules as v1.1.0: check `column_exists` / `table_exists` first,
      idempotent, no drops, no type changes):

      `sales_invoices` — add:
      | Column | Type | Default |
      |---|---|---|
      | `status` | String(20) | `'ACTIVE'` |
      | `cancelled_date` | DateTime | NULL |
      | `cancelled_by` | String(50) | NULL |
      | `cancellation_reason` | String(500) | NULL |

      `sales_invoice_audit` — add:
      | Column | Type | Default |
      |---|---|---|
      | `action` | String(20) | `'EDIT'` |

      `company_profile` (from Milestone 25) — add:
      | Column | Type | Default |
      |---|---|---|
      | `gst_filed_upto_date` | DateTime | NULL |

      **The `status` default of `'ACTIVE'` is what makes existing invoices
      behave unchanged** (Rule B). Every pre-patch invoice becomes ACTIVE
      automatically and every report that filters on status keeps showing it.

      `action` defaulting to `'EDIT'` means the audit rows v1.1.0 already
      wrote are correctly labelled as edits with no backfill needed.

- [ ] Add `'SALE_CANCELLATION'` to the `reference_type` constant list, for
      both the reversing stock rows and the reversing journal entry.

### The service

- [ ] `SalesService.cancel_invoice(session, invoice_id, reason, cancelled_by)`
      — entirely inside **one** database transaction:

      1. Load the invoice. Run every guard below; abort before any write.
      2. Capture a `before_snapshot` as JSON.
      3. For each OUT stock row of this invoice **where `is_reversed` is
         False**, write a reversing **IN** of the same quantity,
         `reference_type='SALE_CANCELLATION'`, `reference_id=invoice_id`,
         dated the **original invoice date**, then set `is_reversed = True`
         on the row just reversed.
         Iterate **per stock row, never grouped by item** — same trap as P3.
      4. For each journal entry of this invoice **where `is_reversed` is
         False**, post a reversing entry (debits and credits swapped),
         `reference_type='SALE_CANCELLATION'`, dated the original invoice
         date, through the existing
         `AccountingService.post_journal_entry()`. Then set
         `is_reversed = True` on the entry just reversed.
      5. Set `status='CANCELLED'`, `cancelled_date`, `cancelled_by`,
         `cancellation_reason`.
      6. **Do not soft-delete the line items.** The invoice must remain
         fully readable after cancellation — an auditor asking about
         invoice 105 should see what it contained.
      7. Write a `sales_invoice_audit` row with `action='CANCEL'`, the
         reason, and both snapshots.
      8. Commit.

      Because this reuses the `is_reversed` flags, an invoice that was
      **edited in v1.1.0 and is now cancelled** reverses only the lines
      currently in force — not the superseded ones. That is the whole point
      of those flags; do not reintroduce "reverse every OUT row".

### Guards — every one of these runs before any write

- [ ] **Already cancelled** → reject. Cancelling twice would reverse nothing
      (all rows already flagged) but would overwrite the cancellation record.
- [ ] **GST return already filed** → reject, with: "GSTR-1 for this period
      has been filed. Issue a credit note instead of cancelling." Enforced
      against `company_profile.gst_filed_upto_date`: reject if the invoice
      date is on or before that date. If the date has never been set, fall
      back to warning the user that it is unset and they should confirm the
      return is unfiled.
- [ ] **Locked period** (`period_locks` from Historical Import H6) → reject.
- [ ] **A receipt exists against this invoice** → **warn, then proceed.**
      Explain plainly: "₹X has been received against this invoice.
      Cancelling it will leave this customer with a credit balance of ₹X,
      to be refunded or set against a future sale." That credit balance is
      the *correct* outcome — the customer really did pay for something that
      no longer exists — so this is a warning, not an error.
- [ ] **Reason is mandatory** and non-empty.
- [ ] **Permission: Administrator only.** Stricter than edit (which allowed
      Accountant too). Enforce in the service, not just by hiding the button.
- [ ] The invoice number is **never freed for reuse.** A new invoice using a
      cancelled number must be rejected by the existing uniqueness check —
      confirm that check does not exclude cancelled rows.

### UI

- [ ] A "Cancel Invoice" action on the sales log / invoice view, visible only
      to an Administrator.
- [ ] A confirmation dialog that **requires the user to type the invoice
      number** to proceed, plus the mandatory reason box. A destructive,
      irreversible action should not be one stray click away.
- [ ] The dialog states in plain words what will happen: the stock goes back
      into inventory, the accounting is reversed, the invoice number stays
      used and cannot be reused, and the invoice stays visible marked
      CANCELLED.
- [ ] After cancelling, regenerate the PDF with a diagonal **"CANCELLED"**
      watermark across the page, so an already-printed or already-saved copy
      cannot be confused with a live invoice.
- [ ] A cancelled invoice is **read-only**: the Edit action must be hidden
      and `update_invoice()` must reject a cancelled invoice.

### Test it: `check_d1.py`

**Stock and books**

- [ ] Item A stock 100, sell 10 → 90. Cancel the invoice → stock reads
      **100**. The original OUT 10 row still exists, flagged `is_reversed`.
- [ ] Multi-line invoice (A × 10, B × 5) cancelled → both A and B return to
      their original levels.
- [ ] After cancellation, the invoice's journal entries **net to zero**, and
      the Trial Balance still balances to the paisa.
- [ ] The customer's outstanding drops by the full invoice total.
- [ ] Reversing stock rows and journal entries carry the **original invoice
      date**, not today's.
- [ ] **The interaction with v1.1.0 edits:** sell 10 → edit to 8 → cancel.
      Stock must read **100**, not 92 and not 108. This is the test that
      proves `is_reversed` is being honoured across both features.

**Guards (each must raise)**

- [ ] cancelling an already-cancelled invoice
- [ ] cancelling an invoice dated on or before `gst_filed_upto_date`
- [ ] cancelling an invoice in a locked period
- [ ] an empty reason
- [ ] a non-Administrator (Accountant, Sales User) calling `cancel_invoice()`
- [ ] calling `update_invoice()` on a cancelled invoice
- [ ] creating a new invoice reusing a cancelled invoice's number

**Warnings (must warn, must not block)**

- [ ] cancelling an invoice that has a receipt against it

**Audit and rollback**

- [ ] `sales_invoice_audit` gains one row with `action='CANCEL'` and both
      snapshots populated
- [ ] the line items are still readable after cancellation
- [ ] **the rollback test:** force a failure part-way through cancellation
      and confirm stock, journals, invoice status and the `is_reversed` flags
      are all exactly as they were before

---

## D2 — Correct a wrong invoice number

The real fix for the problem that prompted this patch. Much simpler than
cancellation: a number is a label, so **nothing about stock or accounting
changes.**

- [ ] `SalesService.correct_invoice_number(session, invoice_id,
      new_invoice_no, reason, modified_by)` — one transaction:
      1. Guards below
      2. Capture `before_snapshot`
      3. Update `invoice_no`
      4. Update the **narration** on the invoice's journal entries if they
         embed the invoice number, so the Day Book and ledgers read
         correctly. Do **not** touch the debit/credit amounts, the stock
         rows, or the entry dates.
      5. Write a `sales_invoice_audit` row with
         `action='NUMBER_CORRECTION'`, the reason and both snapshots
      6. Commit
      7. Regenerate the PDF under the corrected number

- [ ] **Guards:**
      - the invoice must be `ACTIVE` — a cancelled invoice's number is
        frozen
      - `new_invoice_no` must not already exist (including on cancelled
        invoices)
      - reject if the invoice date is on or before
        `gst_filed_upto_date` — once filed, the number is in the return and
        an amendment is the correct route, not a quiet edit
      - reject if the invoice date is in a locked period
      - reason is mandatory
      - **Administrator only**
      - the new number must pass the same format validation as a new invoice

- [ ] UI: a "Correct Invoice Number" action next to Edit, Administrator only,
      with the old number shown read-only beside the new one and a mandatory
      reason. The dialog should say plainly that this changes only the
      number — stock and accounts are untouched.

- [ ] **Test it:** `check_d2.py`
      - correcting a number leaves stock **completely unchanged** (assert the
        stock transaction count and current stock are identical before and
        after)
      - the journal entry amounts and dates are unchanged; only the narration
        differs
      - the corrected number appears in the sales log, the PDF and the
        customer ledger
      - correcting to a number that already exists raises
      - correcting to a number held by a **cancelled** invoice raises
      - correcting a cancelled invoice raises
      - correcting an invoice dated on or before `gst_filed_upto_date` raises
      - a non-Administrator raises
      - `sales_invoice_audit` holds a row with `action='NUMBER_CORRECTION'`

---

## D3 — Making cancellation visible everywhere it should be

The part most likely to be missed, and the one that produces wrong reports if
it is.

**The good news first:** because cancellation posts reversing stock rows and
reversing journal entries, every **financial** report self-corrects with no
changes at all. The Trial Balance, P&L, Balance Sheet, customer outstanding
and stock figures are all already right, because they are sums over ledgers
that now contain the reversals.

**What does need changing** is every report that lists *documents*, because a
cancelled invoice is still a row in `sales_invoices`.

- [ ] **Sales Log** — show cancelled invoices, clearly marked (a CANCELLED
      status column, the row greyed or struck through) with a filter to show
      or hide them. Do not hide them outright: the user needs to see that 105
      exists and is void.
- [ ] **Sales Register** — exclude cancelled invoices from the totals, and
      list them in a separate section at the bottom so the document trail is
      complete.
- [ ] **GST Sales Register, HSN Summary, GSTR-1 and GSTR-3B** — exclude
      cancelled invoices from all taxable value and tax totals. In the GSTR-1
      output, list cancelled invoices separately and clearly labelled rather
      than silently dropping them.
- [ ] **Item-wise and customer-wise sales reports** — exclude cancelled.
- [ ] **Dashboard figures** (sales today / this month) — exclude cancelled.
- [ ] **New: Cancelled Invoices report** — date, number, customer, amount,
      who cancelled it, when, and the reason. Excel and PDF export. This is
      what you hand an auditor who asks about invoice 105.
- [ ] **New: Invoice Sequence Check report** — for a chosen date range, list
      any **missing** numbers in the series. Should be empty if the system has
      been used properly, since cancelled numbers stay in the sequence.
      Genuinely useful before filing, and it proves the no-gaps property
      rather than assuming it.

**Audit the whole reporting layer for this.** Every query that reads
`sales_invoices` either needs a `status` filter or a deliberate decision that
it does not. Go through them one at a time rather than guessing — a cancelled
invoice quietly inflating the GST register is exactly the kind of error that
surfaces at filing time.

- [ ] **Test it:** `check_d3.py`
      - create two invoices, cancel one; the Sales Register total equals only
        the active one
      - the GST register and HSN summary totals exclude the cancelled one
      - the GSTR-3B outward taxable supplies figure excludes it
      - the Sales Log still shows it, flagged CANCELLED
      - the Cancelled Invoices report shows exactly one row, with the reason
      - the Sequence Check report reports **no gaps** after a cancellation

---

## D4 — Settings, documentation and release

### The "GST filed up to" setting

- [ ] Add a **GST returns filed up to** date field to the Settings screen
      (Milestone 25's company profile), Administrator only, with a one-line
      explanation: "Set this to the last date for which you have filed
      GSTR-1. Invoices on or before this date cannot be cancelled or
      renumbered."
- [ ] `SettingsService` reads and writes it; `SalesService` reads it for the
      guards in D1 and D2.
- [ ] If it has never been set, the guards warn rather than block, and the
      Settings screen shows a gentle prompt to set it.

This one field is what turns the GST guards from a nag into a real control.
Worth telling the user to update it each month after filing.

### Documentation

- [ ] `CLAUDE.md` — add to the patching rules: cancellation is soft, invoice
      numbers are never reused, and financial reports self-correct through
      reversing entries while document listings need a `status` filter.
- [ ] `ROADMAP.md` — record v1.2.0 under maintenance patches.
- [ ] `PROJECT_MEMORY.md` — update build status; add to the decisions
      section: *cancel, never delete; the number stays in the sequence;
      number-correction exists separately for typos*. Add to the gotcha
      table: *"every query reading `sales_invoices` needs a `status` filter
      or a deliberate decision not to have one."*
- [ ] `progress.md` — v1.2.0, with the remaining limitations: no sales-side
      credit note yet (so a filed-period invoice still cannot be voided in
      the software), purchase invoices still cannot be cancelled or edited,
      receipts cannot yet be reversed.
- [ ] `CHECKLIST_PATCH_V1_2.md` — tickable D1–D4.

### Build and release

Follow **`RELEASE_PROCESS.md`** — it is the standing process and nothing
about it changes here. The v1.2.0 specifics:

- [ ] `APP_VERSION = "1.2.0"`
- [ ] add `migrations.m004_invoice_cancellation` to the `.spec`
      `hiddenimports`
- [ ] the upgrade test in RELEASE_PROCESS Step 3 must run against a restored
      copy of **v1.1.0 live data**, not a fresh database — the point is to
      prove that invoices created and edited under v1.1.0 cancel correctly
- [ ] one extra upgrade check: a pre-patch invoice must come out of the
      migration with `status = 'ACTIVE'` and appear in every report exactly
      as it did before
- [ ] zip as `GeminiERP_Update_1.2.0.zip`, update the version and the
      "What's new" section in `UPDATE_INSTRUCTIONS.txt`, archive the v1.1.0
      zip for rollback

---

## Deliberately NOT in this patch

- **Cancelling an invoice in a filed GST period.** Blocked by design. The
  correct instrument is a sales-side credit note, which does not exist yet
  and should be its own feature — the mirror of the supplier credit note
  built in v1.1.0's P4.
- **Hard delete.** Not built, and should not be. If a row ever genuinely must
  go, that is a one-off database operation done deliberately against a
  backup, not a button in the application.
- **Reusing a cancelled invoice number.** Prevented.
- **Cancelling or editing purchase invoices.** The same pattern applies and
  should reuse this design when added.
- **Reversing a receipt or payment.** Needed before a cancellation with money
  against it can be fully tidied up; note it as a follow-up.

---

## Sources

- Rule 46(b), CGST Rules 2017 — tax invoices require a consecutive serial
  number, unique within the financial year, up to 16 characters
- Cancelled invoices remain within the consecutive sequence and are listed
  separately in GSTR-1 rather than removed, so cancelling does not create a
  gap in the numbering
- Once GSTR-1 for a period has been filed, an invoice in that return cannot
  be cancelled; the correction route is a credit note in a subsequent return
- For businesses under e-invoicing, an e-invoice can be cancelled on the IRP
  only within 24 hours of generation; after that, a credit note or amendment
  applies. Confirm with the accountant whether the business is within the
  e-invoicing turnover threshold — if it is, cancellation in this software
  must be accompanied by cancellation on the IRP within that window

Reference reading:
[Commentary on Tax Invoice Number Under GST](https://taxguru.in/goods-and-service-tax/commentary-tax-invoice-number-gst.html) ·
[Cancelled Invoice in GSTR-1](https://piceapp.com/blogs/cancelled-invoice-in-gstr1/) ·
[When Can a Tax Invoice Be Cancelled?](https://www.captainbiz.com/blogs/when-can-a-tax-invoice-be-cancelled/) ·
[E-Invoice Cancellation vs Amendment: the 24-hour rule](https://www.gimbooks.com/blog/e-invoice-cancellation-vs-amendment-time-limit/)
