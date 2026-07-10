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

3. **Authentication model (blocks M26/M27).**
   - **App-level users in our own `users` table with hashed passwords (bcrypt
     via `passlib`) — portable, matches the spec's Users/Roles tables, works the
     same on SQLite dev and MSSQL prod.**
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

## Milestone 24 — SQL Server migration (config-driven DB)

- [ ] Make the DB connection **configurable** instead of hardcoded SQLite in
      `database.py`: read a `GEMINI_DB_URL` env var (or a `settings.ini`),
      defaulting to the current SQLite file so dev is unchanged. One code path,
      two backends (the SQLAlchemy payoff).
- [ ] Add the driver to a new `requirements` entry (`pyodbc`) and document
      installing **ODBC Driver 18 for SQL Server** + building the MSSQL URL
      (`mssql+pyodbc://user:pass@host/GeminiERP?driver=ODBC+Driver+18+for+SQL+Server`)
      in `README.md`.
- [ ] Audit models for SQLite-only assumptions (e.g. `Numeric`/`Text`/`Boolean`/
      `DateTime` all map cleanly; check any default/`autoincrement` reliance).
      Fix anything MSSQL rejects.
- [ ] `create_db.py` runs against MSSQL: point `GEMINI_DB_URL` at a SQL Server
      Express instance, create all tables + `ensure_system_accounts()`.
- [ ] **Optional data migration script** — copy existing SQLite rows into MSSQL
      (per-table, respecting FK order) for anyone who wants their dev data; a
      fresh MSSQL start is also fine (dev fixtures are disposable).
- [ ] **Test it:** with `GEMINI_DB_URL` pointed at SQL Server, run a subset of
      the existing `check_milestone*.py` scripts (e.g. M3 sale loop, M7 purchase,
      M11 accounting) and confirm identical behaviour to SQLite — same stock
      math, same balanced journal entries. Behaviour parity across backends is
      the whole goal of this milestone.

---

## Milestone 25 — Company profile, Settings & Backup/Restore

- [ ] `models/company_profile.py` — a single-row `CompanyProfile` (name, address,
      GSTIN, state, bank details, logo path) replacing the hardcoded
      `reports/company_info.py` placeholder; `SettingsService` to read/update it.
- [ ] `ui/settings.py` — a "Settings" screen (top-level tab, matches the spec
      nav) to edit the company profile; PDF/report code reads from the DB
      instead of the module constants.
- [ ] **Backup / Restore** (spec Module 1 + Non-Functional "daily backups"):
      a `BackupService` — for MSSQL, trigger a `BACKUP DATABASE`/restore (or
      document SQL Server Agent daily jobs); for SQLite dev, copy the file.
      A "Backup now" button in Settings + guidance for scheduling daily backups.
- [ ] (Optional, spec Module 1) Financial-year management + locking of closed
      years — can be split to its own milestone if it grows.
- [ ] **Test it:** update the company profile in Settings -> generate a sales
      invoice PDF (Milestone 4 path) and confirm it uses the new details; run a
      backup and confirm the artifact is produced.

---

## Milestone 26 — Users & Roles (data + auth service)

- [ ] `models/role.py` — `Role`: `id`, `name` (`'Administrator' | 'Accountant'
      | 'Inventory Manager' | 'Sales User'`), `permissions` (JSON/text list of
      allowed module keys) + audit.
- [ ] `models/user.py` — `User`: `id`, `username` (unique), `password_hash`,
      `full_name`, `role_id` (FK), `is_active` + audit. NEVER store plaintext.
- [ ] Register both; `create_db.py` creates the tables and seeds the 4 roles
      with their permission sets (Administrator=all; Accountant=Accounts/
      Purchases/Sales/Reports; Inventory Manager=Inventory/Purchases/Stock
      Reports; Sales User=Sales/Customers/Sales Reports) — idempotent, like
      `ensure_system_accounts`.
- [ ] `services/auth_service.py` — `AuthService`: `create_user(...)` (hashes via
      `passlib`/bcrypt), `authenticate(username, password) -> User | None`,
      `has_permission(user, module_key) -> bool`. Seed a default admin on first
      run (force password change later).
- [ ] **Test it:** `check_milestone26.py` — create a user, authenticate with the
      right/wrong password (only the right one succeeds), confirm the stored hash
      is not the plaintext, and assert each role's `has_permission` matches its
      allowed modules.

---

## Milestone 27 — Login + Role-Based Access Control (UI + wiring)

- [ ] `ui/login.py` — a login dialog shown before `MainWindow`; on success it
      holds the current `User` in an app-level session/context object.
- [ ] Wire `created_by` / `modified_by` on every save to the logged-in user's
      username (services currently take a free `created_by` string / None) —
      pass the current user through the UI -> service calls.
- [ ] Enforce RBAC in `main.py`: build only the tabs the user's role permits
      (Administrator sees all; others per their permission set), or disable them.
      A non-admin must not reach a screen their role excludes.
- [ ] **Test it:** `check_milestone27.py` (headless, like M23) — log in as each
      seeded role and assert the visible tab set matches the role; create an
      invoice while logged in and assert its `created_by` is that user.

---

## Milestone 28 — Remote access & deployment (infra + packaging)

*Largely infrastructure + a decision (see Decision 4); lighter on new code.*

- [ ] Point multiple client installs at ONE shared SQL Server via
      `GEMINI_DB_URL` (proven in M24); document the LAN setup in `README.md`.
- [ ] **Concurrency hardening** (see cross-cutting concerns): add the
      `UNIQUE(invoice_no)` constraint + race-safe invoice numbering, and decide
      the oversell policy; add a small concurrent-write test.
- [ ] **Packaging** (spec Tech stack: PyInstaller + Windows Installer): build a
      one-file/one-folder EXE and a Windows installer so non-technical users can
      install the client; bundle the ODBC-driver install step in the docs.
- [ ] Secure remote access: document VPN-based access to the LAN SQL Server (do
      NOT expose SQL Server to the internet directly — Decision 4).
- [ ] **Test it:** two client instances against the same MSSQL server can both
      bill concurrently without duplicate invoice numbers or stock corruption
      (scripted two-process test).

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
