"""Numbered schema migrations (see services/migration_service.py).

Rules for every module here (INSTRUCTIONS_PATCH_V1_1.md, Rule A):
- ADDITIVE ONLY: add a column (nullable, or NOT NULL with a default) or add a
  table. Never drop, rename or retype a column, and never delete rows.
- IDEMPOTENT: check column/table existence before acting, so a re-run is a no-op.
- Expose ``VERSION`` (zero-padded string), ``DESCRIPTION`` and
  ``upgrade(connection, dialect_name)``; never commit — the runner does.

To add a migration: create mNNN_<name>.py, append its name below, and add
``migrations.mNNN_<name>`` to hiddenimports in gemini_erp.spec (modules are
imported by name at runtime, so PyInstaller cannot find them on its own).
"""

MIGRATION_MODULES = [
    "m001_purchase_discounts",
    "m002_sales_invoice_audit",
    "m003_supplier_credit_notes",
]
