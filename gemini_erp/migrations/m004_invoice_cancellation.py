"""Patch v1.2.0 / D1+D4: cancel a sales invoice; the "GST filed up to" date.

- sales_invoices.status NOT NULL DEFAULT 'ACTIVE' — every pre-patch invoice
  becomes ACTIVE automatically, so every report filtering on status keeps
  showing it (Rule B); plus cancelled_date / cancelled_by / cancellation_reason
- sales_invoice_audit.action NOT NULL DEFAULT 'EDIT' — the rows v1.1.0 wrote
  are correctly labelled as edits with no backfill
- company_profile.gst_filed_upto_date (NULL = never set)
"""

from services.migration_service import MigrationService

VERSION = "004"
DESCRIPTION = "Sales invoice cancellation status, audit action, GST filed-up-to date"

_COLUMNS = [
    # (table, column, sqlite definition, mssql definition)
    ("sales_invoices", "status",
     "status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'",
     "status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'"),
    ("sales_invoices", "cancelled_date",
     "cancelled_date DATETIME NULL",
     "cancelled_date DATETIME NULL"),
    ("sales_invoices", "cancelled_by",
     "cancelled_by VARCHAR(50) NULL",
     "cancelled_by VARCHAR(50) NULL"),
    ("sales_invoices", "cancellation_reason",
     "cancellation_reason VARCHAR(500) NULL",
     "cancellation_reason VARCHAR(500) NULL"),
    ("sales_invoice_audit", "action",
     "action VARCHAR(20) NOT NULL DEFAULT 'EDIT'",
     "action VARCHAR(20) NOT NULL DEFAULT 'EDIT'"),
    ("company_profile", "gst_filed_upto_date",
     "gst_filed_upto_date DATE NULL",
     "gst_filed_upto_date DATE NULL"),
]


def upgrade(connection, dialect_name):
    for table, column, sqlite_def, mssql_def in _COLUMNS:
        MigrationService.add_column_if_missing(
            connection, dialect_name, table, column, sqlite_def, mssql_def
        )
