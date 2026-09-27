"""Patch v1.1.0 / P3: edit an existing sales invoice (reverse, then re-post).

- new table sales_invoice_audit (who/when/why + before/after JSON snapshots)
- sales_invoices.edit_count / last_edited_date
- stock_transactions.is_reversed and journal_entries.is_reversed — these two
  flags are what make a SECOND edit safe: only rows not yet reversed are
  reversed again (the "second-edit trap").
"""

from models import SalesInvoiceAudit
from services.migration_service import MigrationService

VERSION = "002"
DESCRIPTION = "Sales invoice edit: audit table, edit counters, is_reversed flags"

_COLUMNS = [
    ("sales_invoices", "edit_count",
     "edit_count INTEGER NOT NULL DEFAULT 0",
     "edit_count INT NOT NULL DEFAULT 0"),
    ("sales_invoices", "last_edited_date",
     "last_edited_date DATETIME NULL",
     "last_edited_date DATETIME NULL"),
    ("stock_transactions", "is_reversed",
     "is_reversed BOOLEAN NOT NULL DEFAULT 0",
     "is_reversed BIT NOT NULL DEFAULT 0"),
    ("journal_entries", "is_reversed",
     "is_reversed BOOLEAN NOT NULL DEFAULT 0",
     "is_reversed BIT NOT NULL DEFAULT 0"),
]


def upgrade(connection, dialect_name):
    # checkfirst makes the CREATE idempotent; the Table object renders the
    # right DDL for either backend.
    SalesInvoiceAudit.__table__.create(connection, checkfirst=True)
    for table, column, sqlite_def, mssql_def in _COLUMNS:
        MigrationService.add_column_if_missing(
            connection, dialect_name, table, column, sqlite_def, mssql_def
        )
