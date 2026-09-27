# PROJECT_MEMORY.md — Gemini ERP

Durable context for anyone (human or Claude Code) picking this project up.
`CLAUDE.md` is the rulebook; `progress.md` is the detailed build log; this file
is the short "what you must know" summary. Created with patch v1.1.0. Earlier
history lives in `progress.md` and the `CHECKLIST_*.md` files.

---

## 1. What this is

A Windows desktop ERP for an Indian trading business in Andhra Pradesh:
items, sales invoices with automatic stock deduction, purchases, GST
(CGST+SGST in-state, IGST out-of-state), double-entry accounting, banking,
GST registers/returns, OCR of supplier bills, users/roles, and a read-only
mobile companion (FastAPI + PWA).

## 2. Stack

Python 3.14 · PySide6 · SQLAlchemy 2 · SQLite (single-user) or SQL Server
(multi-user, `GEMINI_DB_URL` in `.env`) · ReportLab · OpenPyXL · PyInstaller
onedir + Inno Setup installer. OCR runs out-of-process under Python 3.13.

## 3. Layout

`gemini_erp/` is the import root (`from services.x import ...`):
`models/` tables only · `services/` ALL business logic · `ui/` screens only ·
`reports/` PDF/Excel · `migrations/` numbered schema migrations (v1.1.0+) ·
`api/` FastAPI companion · `check_*.py` milestone checks · `version.py`.

## 4. Rules that matter most (details in CLAUDE.md)

- Stock is never stored: `opening + Σ IN − Σ OUT` over `stock_transactions`.
- An invoice's header, lines, stock rows and journal entry commit together or
  not at all.
- No business logic in the UI.
- Since v1.1.0: every schema change is an additive, idempotent, numbered
  migration; existing rows must compute as before; the app backs up before
  migrating.

## 5. Environments

- `gemini_erp/.env` on the dev machine points at the LIVE SQL Server
  `GeminiERP` database (`HP\GEMINI`). **Do not run checks against it.** The
  v1.1.0 checks force a throwaway SQLite (`GEMINI_DB_URL` set before
  `database` is imported; `load_dotenv` does not override it). Older
  `check_*.py` files use whatever `.env` says: set `GEMINI_DB_URL` to a
  temporary SQLite first.
- `gemini_erp/gemini_erp.db` is a pre-v1.1.0 SQLite dev database full of test
  fixtures. It is the reference "pre-patch" database for
  `check_upgrade_path.py`, which only ever works on a copy.

## 6. Gotchas (each one has bitten this project)

| Gotcha | Consequence | What we do |
|---|---|---|
| `create_all()` does not add columns to existing tables — schema changes need a migration | "Invalid column name" on a user's existing database | Numbered migration in `migrations/` (v1.1.0+) |
| Python's sqlite3 runs `ALTER TABLE` in autocommit | A failed migration's DDL is not rolled back | `MigrationService` runs SQLite migrations on an engine that emits `BEGIN` itself |
| `initialize_database()` writes (new tables, seeds) | A backup taken after it is not a true pre-patch copy | Startup backs up BEFORE bootstrap when migrations are pending |
| Modules imported by name at runtime (passlib's bcrypt handler, `migrations.mNNN_*`) | Missing from the PyInstaller build → crash only in the .exe | List them in the `.spec` `hiddenimports` |
| `bcrypt` 4.1+ breaks passlib 1.7.4 | Login fails | `bcrypt==4.0.1` pinned |
| Old SQLite dbs store `stock_transactions.date` as `'YYYY-MM-DD 00:00:00.000000'` | ORM Date parse crash when loading those rows | SQLite `DATE(regexp=...)` variant on the column (read-side only) |
| MSSQL driver rejects a plain `date` bound to a DateTime column | Insert fails on SQL Server only | Business dates are `Date` columns |
| SQL Server allows one NULL in a UNIQUE column | Second NULL code fails | Filtered unique index (`WHERE code IS NOT NULL`) |
| SQL Server `ALTER TABLE ... ADD` has no `COLUMN` keyword | DDL error on MSSQL only | `MigrationService.add_column()` handles both |
| Bare `Numeric()` fails on SQL Server | DDL error | Always `Numeric(p, s)` |

## 7. Build status (2026-09-27)

- Phases 1–4 complete; historical import H1–H6 complete (see `progress.md`).
- **v1.1.0 built and checked** (`CHECKLIST_PATCH_V1_1.md`): migration
  framework, purchase discounts, sales invoice edit, supplier credit notes.
  `check_p1..p4`, `check_patch_ui`, `check_upgrade_path` pass; the built exe
  was tested by the owner and works. Still to do before updating the
  multi-user install: rehearse the upgrade on a restored COPY of the SQL
  Server database.
- **Deferred:** GSTR-3B ITC does not yet net off Input GST reversed by GST
  credit notes — waiting on the accountant (see `CHECKLIST_PATCH_V1_1.md`).
- Open: sales discounts, Purchase Return, sales credit notes / cancellation,
  purchase edit on the reverse-and-re-post design, AI reports.

## 8. Decisions (do not re-litigate without asking)

- **Invoice edits reverse and re-post; they never delete.** Original stock rows
  and journals stay; reversing rows (`SALE_EDIT_REVERSAL`) are dated like the
  original; `is_reversed` stops a second edit from reversing a row twice. A
  removed line needs no code path. Do not replace this with a diff of old vs
  new lines.
- **Invoice number is locked on edit; the date can move only within its
  month;** a Sales User cannot edit (enforced in the service).
- **Two kinds of supplier credit note:** GST (Section 34) credits Discount
  Received with the taxable value and reverses Input GST; COMMERCIAL
  (Circular 251/08/2025) credits Discount Received with the total and touches
  no GST ledger. The type is mandatory with no default. Credit notes never
  touch stock — goods returns go through Purchase Return.
- **On-invoice purchase discounts reduce the taxable value BEFORE GST.** The
  bill-level special discount is apportioned across lines by net value (the
  last line takes the rounding remainder). No discount ledger for these.
- **Migrations are hand-rolled and additive-only** (not Alembic). Rollback =
  restore the automatic backup; no downgrade migrations.
- Oversell is allowed but warned, on new sales and on edits alike.
