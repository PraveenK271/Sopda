"""Patch v1.1.0 / P4: credit notes received from suppliers (discounts only)."""

from models import SupplierCreditNote

VERSION = "003"
DESCRIPTION = "Add supplier_credit_notes table"


def upgrade(connection, dialect_name):
    SupplierCreditNote.__table__.create(connection, checkfirst=True)
