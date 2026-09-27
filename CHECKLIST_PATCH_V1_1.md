# CHECKLIST_PATCH_V1_1.md — Gemini ERP Patch v1.1.0

Tickable version of `INSTRUCTIONS_PATCH_V1_1.md`. Build order P1 → P5, same
rule as every checklist: **build → test → confirm → next.**

This ships as a **patch to an existing installation** — nothing may destroy,
alter or orphan an existing row. Patching rules A/B/C are in `CLAUDE.md`.

All `check_*.py` below force a throwaway SQLite database, so they are safe to
run on the dev machine (whose `.env` points at the live SQL Server).

---

## P1 — Migration framework

- [x] `models/schema_migration.py` — `SchemaMigration` (version unique, description,
      applied_date, applied_by + audit columns)
- [x] `migrations/` package: `m001_purchase_discounts`, `m002_sales_invoice_audit`,
      `m003_supplier_credit_notes`, each with `VERSION`, `DESCRIPTION`,
      `upgrade(connection, dialect_name)`; order in `migrations/__init__.py`
- [x] `services/migration_service.py` — `get_applied_versions`,
      `get_pending_migrations`, `run_pending` (own transaction each, recorded in
      the same transaction, stops at first failure naming the version),
      `column_exists`, `table_exists`, `add_column` (SQLite `ADD COLUMN` vs
      SQL Server `ADD`)
- [x] Real transactional DDL on SQLite (driver autocommits `ALTER` otherwise)
- [x] Every migration idempotent (checks before acting)
- [x] `BackupService.auto_backup_before_migration(reason)` →
      `backups/pre_patch_<version>_<timestamp>.db` / SQL Server `.bak`; raises on failure
- [x] Startup wiring in `main._prepare_database`: pending check → modal
      "Updating database" → backup → create_all/seeds (`ensure_roles_and_admin`)
      → migrations → summary; on failure show error + backup and exit.
      (Backup moved BEFORE bootstrap — see progress.md.)
- [x] `.spec`: `migrations/` in `datas`, each module in `hiddenimports`
- [x] **Test:** `check_p1.py` — fresh db applies + records all; second run is a
      no-op; `column_exists` known/unknown; failing migration not recorded, its
      ALTER rolled back, run stops; backup written

## P2 — Discount and Special Discount on purchases

- [x] Migration 001 (all NOT NULL DEFAULT 0): `purchase_invoice_items.discount_percent`
      NUMERIC(5,2), `discount_amount` NUMERIC(15,2); `purchase_invoices.special_discount`,
      `total_discount` NUMERIC(15,2)
- [x] Models updated with explicit precision
- [x] `calculate_purchase()` — line %, apportioned special discount (last line
      takes the remainder), GST per line on the post-discount taxable value
- [x] Guard rails: 0–100 %, special ≤ net value, blank/None/"" = 0
- [x] `create_purchase_invoice` / `update_purchase_invoice` accept the optional
      fields; journal posts net Purchase + net Input GST, no discount ledger
- [x] Purchase screen: Disc % per line, Special Discount field, live
      Gross → Discount → Taxable → GST → Net panel
- [x] Purchase detail ("print") view shows discount columns / special discount
      only when non-zero (the app has no purchase PDF)
- [x] Purchase Register / HSN / supplier reports show net figures
- [x] Sales-side discounts recorded as out of scope in `progress.md`
- [x] **Test:** `check_p2.py` — no-discount bill identical to pre-patch (Rule B);
      10 × 100 less 10 % → taxable 900; two GST rates + special discount sum to
      the paisa; 150 % rejected; special > net rejected; blanks = 0; journal
      balances and Input GST = net GST

## P3 — Edit an existing sales invoice

- [x] Migration 002: `sales_invoice_audit`; `sales_invoices.edit_count`,
      `last_edited_date`; `stock_transactions.is_reversed`, `journal_entries.is_reversed`
- [x] `SALE_EDIT_REVERSAL` reference type (stock rows + journal)
- [x] `SalesService.update_invoice()` — one transaction: checks, snapshot, reverse
      un-reversed OUT rows per row (dated like the original) + flag, reverse
      un-reversed journals via `post_journal_entry` + flag, soft-delete old lines,
      re-post with the shared GST logic, header + `edit_count` + `last_edited_date`,
      audit row, commit
- [x] Blocks: invoice_no change, no lines, locked period, other month, empty
      reason, non-Administrator/Accountant (in the service)
- [x] Warns (does not block): earlier month, customer change, receipts recorded
- [x] Oversell on edit follows the normal sale policy (warn), returning stock counted once
- [x] Soft-deleted item still accepts its reversing IN; only new lines are validated
- [x] UI: Edit button (Administrator/Accountant only) → Billing pre-filled,
      invoice_no read-only, mandatory reason, warnings confirmed, PDF offered
- [x] Edit History view (who / when / why / before → after)
- [x] Invoice PDF and details show only current (non-deleted) lines
- [x] Out-of-scope items recorded in `progress.md`
- [x] **Test:** `check_p3.py` — stock matrix rows 1–8 (row 8 = 94), accounting
      nets + TB, originals kept, reversal dates, AP → KA customer switch to IGST,
      every guard, every warning, audit rows = edit_count, byte-for-byte rollback

## P4 — Credit Notes received from suppliers

- [x] Migration 003: `supplier_credit_notes` (unique per supplier + number)
- [x] `DISCOUNT_RECEIVED` system account (INCOME), seeded idempotently
- [x] `CreditNoteService`: `create_credit_note`, `list_credit_notes`,
      `update_ims_status`; GST vs commercial journals via `post_journal_entry`,
      `reference_type='SUPPLIER_CREDIT_NOTE'`
- [x] Validation: type mandatory; GST parts = total within Rs 1; state rule
      (CGST+SGST in-state / IGST out-of-state, never both); commercial has no GST;
      linked-invoice over-total warns; GOODS_RETURN refused with the Purchase Return message
- [x] UI `ui/credit_notes.py` under Purchases: type selector with plain-English
      help switching GST fields; list with IMS status; Update IMS status action
- [x] Credit Notes Received Register — Excel + PDF; filters for IMS-pending and
      pending notes near/past the 30 November cut-off
- [x] Supplier Outstanding / Supplier Ledger include notes (via the journal — tested)
- [x] **Test:** `check_p4.py` — GST 1,180 and commercial 1,180 postings, journals
      and TB balance, every rejection, same number under two suppliers accepted,
      outstanding drops, no stock touched

## P5 — Documentation, packaging and release

- [x] `CLAUDE.md` — Patching rules (A, B, C); every schema change needs a migration
- [x] `ROADMAP.md` — Maintenance patches, v1.1.0, what remains open
- [x] `PROJECT_MEMORY.md` — created (did not exist): build status, decisions, gotcha table
- [x] `progress.md` — v1.1.0 shipped + known limitations
- [x] `CHECKLIST_PATCH_V1_1.md` — this file
- [x] `DISTRIBUTION_README.md` — updating from an earlier version, backup
      location, rollback plan
- [x] `APP_VERSION = "1.1.0"` in `version.py`; title bar + Settings; `installer.iss` 1.1.0
- [x] `.spec` updated (migrations in `datas` + `hiddenimports`)
- [x] Upgrade path tested from source: `check_upgrade_path.py` on a copy of the
      pre-patch dev database — backup byte-identical, 243 rows unchanged,
      totals/stock/TB identical, then all three features with the TB balanced
- [x] Fresh install tested from source (`check_p1`, `check_patch_ui` [1])
- [x] **Manual:** `build.bat`, then the built `GeminiERP.exe` tested by the
      owner — all changes present and working as expected (2026-09-27)
- [x] **Manual:** on-screen look at Purchases (discounts), Billing edit mode,
      Edit History, Credit Notes
- [x] Billing line-entry row given the same widths as Purchases (Item dropdown
      320px min + stretch, Qty/Rate 80px) — the earlier layout commit had only
      changed Purchases
- [ ] **Manual:** on SQL Server, run `check_upgrade_path`-style steps against a
      RESTORED COPY of the live database (never the live one) before updating
      the multi-user install

## Deferred (revisit later — needs the accountant)

- [ ] **GSTR-3B ITC vs GST credit notes.** `GstReportService.get_gstr3b_summary()`
      takes ITC from purchase invoices only; it does not net off the Input GST
      reversed by GST-type supplier credit notes (the ledgers already do).
      Decide with the accountant how reversals should appear (reduce table 4
      ITC available vs report as ITC reversed) before changing the report.

---

## Patch v1.1.0 is DONE when

A user with existing live data installs the new folder over their old one,
launches it, sees a one-time database update, and finds every pre-existing
invoice, stock figure and ledger balance exactly as they left it — and can
then record a discounted purchase, correct a sales invoice, and enter a
supplier credit note, with the books balanced after each.
