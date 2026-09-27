"""Patch v1.1.0 / P2: line discount + special discount on purchase invoices.

Every column is NOT NULL DEFAULT 0, so existing rows are back-filled with 0 and
every pre-patch bill computes to exactly the same totals (Rule B).
"""

from services.migration_service import MigrationService

VERSION = "001"
DESCRIPTION = "Add discount fields to purchase invoices"

_COLUMNS = [
    # (table, column, sqlite definition, mssql definition)
    ("purchase_invoice_items", "discount_percent",
     "discount_percent NUMERIC(5,2) NOT NULL DEFAULT 0",
     "discount_percent NUMERIC(5,2) NOT NULL DEFAULT 0"),
    ("purchase_invoice_items", "discount_amount",
     "discount_amount NUMERIC(15,2) NOT NULL DEFAULT 0",
     "discount_amount NUMERIC(15,2) NOT NULL DEFAULT 0"),
    ("purchase_invoices", "special_discount",
     "special_discount NUMERIC(15,2) NOT NULL DEFAULT 0",
     "special_discount NUMERIC(15,2) NOT NULL DEFAULT 0"),
    ("purchase_invoices", "total_discount",
     "total_discount NUMERIC(15,2) NOT NULL DEFAULT 0",
     "total_discount NUMERIC(15,2) NOT NULL DEFAULT 0"),
]


def upgrade(connection, dialect_name):
    for table, column, sqlite_def, mssql_def in _COLUMNS:
        MigrationService.add_column_if_missing(
            connection, dialect_name, table, column, sqlite_def, mssql_def
        )
