# CHECKLIST_PHASE4.md — Phase 4: Going Multi-User

PLANNING DOCUMENT — nothing in this file has been built yet. This is the
Phase 4 scope from `ROADMAP.md` ("Going multi-user"):

- Switch the database from SQLite to **Microsoft SQL Server** (mostly a
  connection-string change because we used SQLAlchemy)
- **Multi-user access and roles** (spec Module 2: User Login + Role-Based
  Access Control; roles: Administrator, Accountant, Inventory Manager, Sales
  User)
- **Remote access**
- **Mobile companion app**

Same rules as every prior checklist (`CLAUDE.md` applies): **build -> test ->
confirm -> next, one milestone at a time.** Milestone numbering continues from
Phase 3 (next is 24). Database-neutral code (SQLAlchemy) is the whole reason the
MSSQL switch is small — keep it that way.

> **Sequencing note:** Phase 3 Part 2 (the AI layer) is deferred pending a
> hardware/provider decision and is NOT a prerequisite for Phase 4 — the two are
> independent. Phase 4 can be built now if desired; it just changes deployment,
> not the AI features.

---

## Decisions needed BEFORE building (confirm with the user)

These materially change the plan. Recommended defaults in **bold**; do not build
the affected milestone until the choice is locked.

1. **SQL Server hosting/edition (blocks M24).**
   - **SQL Server Express on a LAN server (free, up to 10 GB/db) — recommended
     for a small trading business: real multi-user over the local network, no
     cloud cost.**
   - Azure SQL / cloud — needed only if remote-access-over-internet is the
     primary goal (ties into M28).
   - A single shared machine everyone RDPs into — then SQLite could even stay,
     but that is not really "multi-user"; MSSQL is still the right call for
     concurrency + scale (100k+ invoices).

2. **Python ↔ SQL Server driver (blocks M24).**
   - **`pyodbc` + Microsoft ODBC Driver 18 for SQL Server — the standard,
     best-supported combo.** (Needs the ODBC driver installed on each client.)
   - `pymssql` — no ODBC driver needed, but less featureful.

3. **Authentication model (blocks M26/M27). — LOCKED: app-level users.**
   - **[CHOSEN] App-level users in our own `users` table with hashed passwords
     (bcrypt via `passlib`) — portable, matches the spec's Users/Roles tables,
     works the same on SQLite dev and MSSQL prod. Built in M26/M27.**
   - Windows/AD integrated auth — nicer for an office domain, but couples us to
     Windows and is harder to test.

4. **Remote access topology (blocks M28).**
   - **LAN-only first (clients on the same network as the SQL Server); add
     secure remote later via VPN.** Simplest, safest.
   - Direct internet-exposed SQL Server — do NOT do this (attack surface); if
     internet remote is required, it should go through a VPN or the future API.

5. **Mobile app shape (blocks M29) — biggest effort, plan separately.**
   - The desktop app is PySide6 (not web), so a mobile app needs a **new REST
     API layer** over the existing services. Recommended: **a read-first PWA /
     companion (dashboards, outstanding, stock, approve-a-scan) backed by a
     FastAPI service reusing the current SQLAlchemy models** — not a full
     data-entry rewrite. Decide scope + tech before planning M29 in detail.

---

## Cross-cutting concerns multi-user introduces (apply throughout Phase 4)

- **Concurrency / race conditions.** Single-user SQLite hid these. Under
  multiple users:
  - Invoice-number generation must be race-safe (a `max(id)+1` or count-based
    scheme will collide). Use a DB sequence / `UNIQUE` constraint on
    `invoice_no` + retry, or a per-series counter row locked in the txn.
  - Stock is computed from `stock_transactions` (good), but two concurrent
    sales can both pass a stock check and oversell — decide whether to enforce
    non-negative stock at commit (row lock / constraint) or allow and warn.
  - Keep the "one transaction = all or nothing" rule (already followed); verify
    isolation level on MSSQL (default READ COMMITTED is fine with explicit txns).
- **Audit columns become real.** `created_by`/`modified_by` are currently free
  strings/None; wire them to the logged-in user (M27). `is_deleted` soft-delete
  stays.
- **Security.** Never store plaintext passwords (hash). SQLAlchemy ORM already
  parameterizes queries (no raw SQL string-building) — keep it that way.
- **Backups.** Spec requires daily backups + crash recovery (M25).

---

## Milestone 24 — SQL Server migration (config-driven DB)  ✅ DONE (2026-07-29)

Locked decisions: **SQL Server Express on the LAN** (instance `HP\GEMINI`,
Windows `Trusted_Connection` auth) via **pyodbc**. The installed client driver
is **ODBC Driver 17** (not 18); the `.env` URL uses Driver 17 accordingly. The
`.env` lives in `gemini_erp/` and is gitignored.

- [x] Made the DB connection **configurable** in `database.py`: `load_dotenv()`
      then read `GEMINI_DB_URL`, defaulting to the SQLite file so dev/packaged
      single-user builds are unchanged. Backend-aware `connect_args`
      (`check_same_thread` for SQLite only). Kept the frozen-aware app-root path.
- [x] Added `pyodbc` + `python-dotenv` to `requirements.txt`. MSSQL URL shape +
      ODBC-driver note documented in `README.md`.
- [x] `create_db.py` prints the backend (`Backend: SQL Server`) so a run can be
      confirmed to have hit MSSQL, not SQLite.
- [x] Added `reset_dev_db.py` (dev utility: drop + recreate on the current
      backend) for rebuilding after a schema/index change. **Destructive — dev
      only.**
- [x] **Model audit — models were already MSSQL-clean** (explicit `String(n)`,
      `Numeric(p,s)`, `Text`, plain `primary_key=True`, no `autoincrement`).
      **Four real incompatibilities surfaced during the check-script run and were
      fixed (no business-logic change):**
  1. **Boolean filters** `.is_(False)` rendered `IS 0`, which MSSQL rejects
     (`IS` needs NULL). Replaced with `== false()`/`== true()` (renders `= 0`,
     valid on both) across 9 services + 3 check scripts. Columns are `NOT NULL`
     so semantics are identical.
  2. **`ledger_accounts.code`** was a nullable `UNIQUE` column; SQL Server allows
     only ONE NULL row there, but customer/supplier subledgers have `code=NULL`.
     Switched to a **filtered unique index** (`WHERE code IS NOT NULL`,
     `mssql_where`/`sqlite_where`) — "unique among non-null codes" on both.
  3. **Aggregate `FILTER (WHERE …)`** in the stock calc (`item_service`) — SQLite
     supports it, MSSQL does not. Rewrote as `SUM(CASE WHEN … THEN qty ELSE 0)`.
  4. **`stock_transactions.date`** was `DateTime` but always stores a calendar
     `date`; the MSSQL pyodbc `DateTime` bind-processor calls `.tzinfo` on a
     `date` and crashes. Changed the column to `Date` (matches every other
     business-date column). Requires a table rebuild (`reset_dev_db.py`).
- [x] `create_db.py` / `reset_dev_db.py` run clean against `HP\GEMINI`, creating
      all 16 tables + `ensure_system_accounts()`.
- [ ] Optional SQLite→MSSQL data-migration script — **skipped** (dev fixtures are
      disposable; fresh MSSQL start chosen).
- [x] **Tested — behaviour parity confirmed both directions:**
      `check_milestone3` (sale loop + stock deduction + GST split CGST/SGST vs
      IGST) and `check_milestone11` (accounting engine, balanced journals) **PASS
      on SQL Server AND on SQLite**, identical numbers (stock 100→90→85, journals
      balanced). `check_b2c_state.py` from the plan doesn't exist; the intra/
      inter-state GST split it referred to is covered inside M3.
      NOTE: `check_milestone2.py` failed on BOTH backends with
      `KeyError: 'current_stock'` — a **pre-existing stale-check bug**, unrelated
      to the DB switch. **Cleaned up after M24** (commit `d3e497e`):
      `ItemService.list_items()` now returns `current_stock` (derived in one
      grouped query; the Items page dropped its per-row N+1), and the check was
      rewritten to use a unique per-run item code — its old fixed-code
      `session.delete()` hard-delete both broke the soft-delete rule and, on SQL
      Server, cascaded a NULL into non-nullable `sales_invoice_items.item_id`.
      PASS on both backends.

---

## Milestone 25 — Company profile, Settings & Backup/Restore  ✅ DONE (2026-07-30)

- [x] `models/company_profile.py` — a single-row `CompanyProfile` (name, address,
      mobile, GSTIN, state, bank details, terms, logo path) replacing the
      hardcoded `reports/company_info.py` placeholder. `services/settings_service.py`
      (`SettingsService`) reads/updates it and returns a plain dict; `ensure_profile()`
      seeds the single row from the old `company_info` constants on first run
      (idempotent, wired into `initialize_database` next to `ensure_system_accounts`).
      `company_info.py` is kept as the **seed defaults only** (no longer read at
      print time).
- [x] `ui/settings.py` — a top-level **"Settings"** tab to edit the company
      profile (+ logo browse, terms one-per-line). `reports/invoice_pdf.py` now
      reads all seller/bank/terms values from `SettingsService.get_profile()`
      (escaped), not the module constants; `services/ocr_service.py` reads *our*
      GSTIN from the profile too.
- [x] **Backup** (spec Module 1 + "daily backups"): `services/backup_service.py`
      (`BackupService`). SQLite → copies the live DB file (from the engine URL, so
      a `GEMINI_DB_URL` override is honoured) to a timestamped `.db` under
      `gemini_erp/backups/`. SQL Server → `BACKUP DATABASE ... WITH INIT, FORMAT`
      to the instance's default backup dir (server-writable), driven on a **raw
      pyodbc cursor** with autocommit and full result-set consumption (going
      through SQLAlchemy's execution layer silently no-ops BACKUP), then
      **`RESTORE VERIFYONLY`** to confirm a valid set was written (the `.bak` lives
      in a server-side ACL'd folder the client can't stat). A **"Backup Now"**
      button in Settings + on-screen guidance to schedule daily backups (Task
      Scheduler for SQLite / SQL Server Agent job for MSSQL — see README). No
      COMPRESSION (unsupported on Express). Restore is documented, not automated
      (needs exclusive DB access — do via SSMS/SQL Agent).
- [ ] (Optional, spec Module 1) Financial-year management + locking of closed
      years — deferred; can be its own milestone if it grows.
- [x] **Tested — `check_milestone25.py`, PASS on SQL Server AND SQLite:** set
      unique markers in the company profile, render an invoice PDF (compression
      off) and assert every marker (name/GSTIN/bank/term) appears in it —
      proving the PDF reads the DB profile; then run a backup and confirm the
      artifact (SQLite: file exists; MSSQL: `RESTORE VERIFYONLY` passes). The
      check restores the original profile afterward. No business logic changed.

---

## Milestone 26 — Users & Roles (data + auth service)  ✅ DONE (2026-07-30)

- [x] `models/role.py` — `Role`: name (unique), `permissions` as a JSON-string
      `Text` column + audit. `models/user.py` — `User`: username (unique),
      `password_hash` (NO plaintext `password` column exists), full_name,
      role_id FK, is_active, `must_change_password`, last_login + audit.
- [x] `services/permissions.py` — module keys + the 4 role permission sets in
      ONE place (Administrator=all; Accountant=accounts/purchases/purchase_log/
      billing/sales_log/gst/documents; Inventory Manager=items/purchases/
      purchase_log/documents; Sales User=billing/sales_log/items). `create_db.py`
      seeds roles + a default admin via `ensure_roles_and_admin` (idempotent,
      like `ensure_system_accounts`).
- [x] `services/auth_service.py` — `AuthService` (bcrypt via passlib,
      `bcrypt==4.0.1` PINNED): hash_password, create_user (validates duplicate +
      min-8 password), authenticate (timing-safe `verify()`, returns None
      identically for unknown-user/wrong-password), change_password,
      admin_reset_password, has_permission, list_users, deactivate_user. Never
      logs a password/hash. Default admin `admin`/`Admin@1234`,
      `must_change_password=True`, seeded only on an empty users table.
- [x] **Tested — `check_milestone26.py` PASS on SQL Server AND SQLite:** all 11
      assertions (idempotency, default admin + flag, hash != plaintext,
      authenticate success/failure/unknown, create_user validation,
      change_password, per-role has_permission).

---

## Milestone 27 — Login + Role-Based Access Control (UI + wiring)  ✅ DONE (2026-07-30)

- [x] `services/session_context.py` holds the current `User` for the process
      (`get_username()` → "system" when logged out). `ui/login.py` (masked
      password, generic "Invalid username or password", 5-attempt/30s lockout,
      Enter submits) + `ui/change_password.py` (forced + non-cancellable when
      `must_change_password`). `main.py` startup: bootstrap → login → forced
      change → MainWindow, with an **Account → Logout** that returns to login
      without restarting (login/exec loop).
- [x] RBAC in `main.py`: only permitted tabs are **built** (a disallowed screen
      is never constructed — not hidden/disabled). Title shows `name (role)`.
      `ui/user_management.py` (Administrator-only "Users" tab; add / reset-
      password / deactivate; never shows a hash).
- [x] `created_by`/`modified_by` wired to `SessionContext.get_username()` at
      every saving UI call site (billing, purchase incl. edit + inline item/
      supplier, items, banking, OCR doc save). Service signatures unchanged.
- [x] **Tested — `check_milestone27.py` PASS on SQL Server AND SQLite:** per-role
      permitted-module sets, created_by wiring stores the logged-in user,
      SessionContext default "system", admin_reset_password forces a change. RBAC
      tab construction per role also verified with an offscreen MainWindow smoke
      test (deleted after passing).
- [ ] **Manual UI checklist (needs a screen — do before deploy):** login shows
      before main window; wrong password → generic error; first admin login
      forces an uncancellable password change; new password works / old fails;
      a Sales User sees only Items/Billing/Sales Log; Logout returns to login.

---

## Milestone 28 — Remote access & deployment (infra + packaging)  ✅ DONE (2026-07-30)

*Largely infrastructure + two decisions (below); lighter on new code.*

**Decisions locked (via the user):** oversell policy = **allow but warn**;
invoice numbering = **keep manual entry** (rely on `UNIQUE(invoice_no)` + a
friendly clash message), NOT auto-generated.

- [x] Multiple clients point at ONE shared SQL Server via each client's `.env`
      `GEMINI_DB_URL` (proven in M24). LAN setup + per-client ODBC-driver step
      documented in `README.md` ("Multi-user deployment").
- [x] **Concurrency hardening:** `UNIQUE(invoice_no)` already existed on
      `sales_invoices`; `SalesService.create_invoice` now catches the resulting
      `IntegrityError` and raises a clear "Invoice number '…' is already used"
      `ValueError` (race-safe manual numbering — the constraint is the authority).
      Oversell is allowed but flagged: the service computes a negative-stock
      warning (`invoice.stock_warnings`, a transient attribute) and Billing shows
      it after saving. Stock stays an append-only log, so concurrent sales don't
      lose updates. One-transaction rule unchanged; default READ COMMITTED is
      correct (noted in README).
- [x] **Packaging** already shipped earlier (PyInstaller onedir `build.bat` +
      Inno Setup `build_installer.bat`/`installer.iss`); README's new section
      references it and the ODBC-driver install step for clients.
- [x] Secure remote access: README documents **VPN-only** access to the LAN SQL
      Server (never expose SQL Server to the internet — Decision 4).
- [x] **Tested — `check_milestone28.py` PASS on SQL Server AND SQLite:** two
      concurrent clients (threads, own sessions) — (A) same invoice_no race →
      exactly one saved, one clean rejection, one row; (B) N concurrent sales of
      one item → stock has no lost updates + N OUT rows; (C) oversell still
      commits and is warned (stock goes negative).

---

## Milestone 29 — Mobile companion app (separate track — plan in detail later)

*Biggest, most separable effort. Needs Decision 5 locked first. This milestone is
a placeholder to be expanded into its own checklist when the time comes.*

- [ ] Stand up a **REST API** (recommended: FastAPI) that reuses the existing
      `services/` + SQLAlchemy models — the desktop app is PySide6, so the mobile
      app cannot talk to the DB directly; an API is the bridge (and doubles as
      the secure remote-access layer).
- [ ] Reuse `AuthService` for API login (token/JWT); enforce the same RBAC.
- [ ] Build the mobile client (PWA or Flutter/React Native per Decision 5),
      read-first: dashboards, outstanding, stock levels, reorder alerts, and
      optionally approve a scanned bill.
- [ ] **Test it:** API endpoints return the same numbers as the desktop reports
      for the same data; the mobile client shows them; auth/RBAC enforced.

---

## Phase 4 is DONE when:

The system runs on Microsoft SQL Server with several users on different machines
logging in with their own accounts, each seeing only what their role permits,
with correct audit trails, safe concurrent billing (no duplicate invoice numbers
or stock corruption), daily backups, a packaged installer for rollout, and a
read-first mobile companion — all without changing the Phase 1-3 business logic,
because the switch was a connection string + an auth/permission layer on top.

---

## Deliberately NOT in Phase 4 (out of scope / future)

- Rewriting the desktop UI as a web app (the mobile app gets an API instead).
- Full mobile data-entry parity (start read-first).
- Internet-exposed SQL Server (VPN/API only).
- The AI layer (Phase 3 Part 2) — tracked separately, deferred to a hardware
  upgrade.
