# CHECKLIST_PATCH_V1_2.md — Gemini ERP Patch v1.2.0

Tickable version of `INSTRUCTIONS_PATCH_V1_2.md`. Build order D1 → D4, same
rule as every checklist: **build → test → confirm → next.**

Prerequisite: the v1.1.0 migration framework. Numbering continues at m004.
It is **cancel, not delete** — the invoice row, lines and original stock /
journal rows all stay, and the number stays in the sequence for good.

All `check_*.py` below force a throwaway SQLite database, so they are safe to
run on the dev machine (whose `.env` points at the live SQL Server).

---

## D1 — Cancel a sales invoice

- [x] `migrations/m004_invoice_cancellation.py` (additive, idempotent):
      `sales_invoices.status` (DEFAULT 'ACTIVE'), `cancelled_date`,
      `cancelled_by`, `cancellation_reason`; `sales_invoice_audit.action`
      (DEFAULT 'EDIT'); `company_profile.gst_filed_upto_date`
- [x] `SALE_CANCELLATION` reference type (stock rows + journal)
- [x] `SalesService.cancel_invoice()` — one transaction; per-stock-row reversal
      of rows not yet reversed, dated like the originals; journal reversal via
      `post_journal_entry`; `is_reversed` flagged; status CANCELLED; lines kept;
      audit row action CANCEL with both snapshots
- [x] Shared `_reverse_postings()` used by edit and cancel
- [x] Guards before any write: already cancelled · GST filed-up-to date
      (block; warn while unset) · locked period · reason · Administrator only
      (in the service) · number never reusable
- [x] Receipt warning names the customer credit balance; warns, never blocks
- [x] `update_invoice()` refuses a cancelled invoice
- [x] UI: "Cancel Invoice" (Administrator only); dialog explains what happens,
      needs the number typed back + a reason; PDF gets a diagonal CANCELLED
      watermark; Edit hidden/disabled for a cancelled invoice
- [x] **Test:** `check_d1.py` — PASS

## D2 — Correct a wrong invoice number

- [x] `SalesService.correct_invoice_number()` — one transaction; number +
      journal narrations only; audit row action NUMBER_CORRECTION
- [x] Guards: ACTIVE only · new number unused incl. cancelled (case-insensitive)
      · GST filed-up-to date · locked period · reason · Administrator only ·
      same format rule as a new invoice
- [x] `validate_invoice_no()` — GST Rule 46(b): ≤ 16 chars, letters / digits /
      `-` / `/`; new invoices, corrections and the import VALIDATE step
- [x] UI: "Correct Invoice Number" beside Edit (Administrator only); old number
      read-only; says stock and accounts are untouched; offers the new PDF
- [x] **Test:** `check_d2.py` — PASS

## D3 — Cancellation visible everywhere

- [x] Every `sales_invoices` reader audited one at a time (table in `progress.md`)
- [x] Sales Log: Status column, greyed + struck through, show/hide filter
- [x] Sales Register: cancelled excluded from totals, listed in a separate section
      (screen and Excel export)
- [x] Sales Register / HSN / GSTR-1 / GSTR-3B outward exclude cancelled; GSTR-1
      lists them separately, labelled
- [x] Dashboard "sales today" (API/PWA) excludes cancelled; PWA marks them
- [x] Item-wise / customer-wise sales reports — none exist in the app (nothing to filter)
- [x] New: Cancelled Invoices report (Excel + PDF)
- [x] New: Invoice Sequence Check (Excel)
- [x] **Test:** `check_d3.py` — PASS

## D4 — Settings, documentation and release

- [x] Settings: "GST returns filed up to" date, explanation, prompt while unset;
      `SettingsService` reads/writes it, Administrator-only in the service
- [x] Startup reordered: backup → create tables → migrations → seeding (the old
      order broke every v1.1.0 → v1.2.0 upgrade — see `progress.md`)
- [x] `CLAUDE.md`, `ROADMAP.md`, `PROJECT_MEMORY.md`, `progress.md`, this file
- [x] `APP_VERSION = "1.2.0"`, `installer.iss` 1.2.0
- [x] `.spec`: `migrations.m004_invoice_cancellation` in `hiddenimports`
- [x] **Test:** `check_v12_ui.py` (offscreen) — PASS
- [x] **Test:** `check_upgrade_path.py` — PASS from the v1.0 dev db and from a
      v1.1.0-era db built by the v1.1.0 code (invoice edited twice, then
      cancelled correctly); every pre-patch invoice ACTIVE and in every report
- [ ] **Manual:** `build.bat`, then the built exe against a restored copy of
      **v1.1.0 live data** (`python check_upgrade_path.py <copy.db>` covers the
      logic; repeat the key steps by hand in the exe)
- [ ] **Manual:** on SQL Server, a restored COPY of the live database (never the
      live one) — migration 004 has only been exercised on SQLite here
- [ ] **Manual:** set "GST returns filed up to" in Settings after updating
- [ ] **Manual / missing files:** the patch text says to follow
      `RELEASE_PROCESS.md` and update `UPDATE_INSTRUCTIONS.txt`, zip as
      `GeminiERP_Update_1.2.0.zip`, and archive the v1.1.0 zip — neither file
      exists in the repository; the zip / archive steps are outside the code

## Deferred / open

- [ ] Sales-side credit note (needed to void an invoice in a filed GST period)
- [ ] Cancel / reverse-and-re-post edit for purchase invoices
- [ ] Reverse a receipt or payment
- [ ] Decide whether invoice EDIT should also be blocked by the GST filed-up-to date
- [ ] e-invoicing: confirm with the accountant whether the IRP 24-hour
      cancellation rule applies to this business
- [ ] (from v1.1.0) GSTR-3B ITC vs GST credit notes — waiting on the accountant
