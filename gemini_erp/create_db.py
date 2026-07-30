"""One-time script: create the SQLite database file and all core tables.

Run with: python create_db.py
"""

from sqlalchemy import inspect, text

from database import Base, DATABASE_PATH, DATABASE_URL, SessionLocal, engine
from models import (  # noqa: F401
    BankAccount,
    BankStatementLine,
    CompanyProfile,
    Customer,
    Document,
    Item,
    JournalEntry,
    JournalEntryLine,
    LedgerAccount,
    Payment,
    PurchaseInvoice,
    PurchaseInvoiceItem,
    Receipt,
    Role,
    SalesInvoice,
    SalesInvoiceItem,
    StockTransaction,
    Supplier,
    User,
)
from services.auth_service import ensure_roles_and_admin
from services.chart_of_accounts import ensure_system_accounts
from services.settings_service import ensure_profile


def _migrate_add_column(table: str, column: str, ddl_type: str) -> None:
    """Add a column to an existing table if it isn't there yet (SQLite-friendly).

    Base.metadata.create_all() never alters existing tables, so columns added
    to a model after its table was first created must be migrated in by hand.
    Idempotent: a no-op once the column exists.
    """
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return  # create_all will build it fresh with the column already present
    existing = {col["name"] for col in inspector.get_columns(table)}
    if column in existing:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
    print(f"Migrated: added {table}.{column}")


def initialize_database() -> None:
    """Create all tables, run in-place migrations, seed system accounts.

    Idempotent: safe to call on every app start (packaged clean machine or an
    existing db alike). ``create_all`` skips tables that already exist and
    ``ensure_system_accounts`` only inserts what is missing, so re-running
    changes nothing on an established database. No printing — see :func:`main`
    for the CLI wrapper (a windowed/packaged app may have no stdout).
    """
    # create_all first so brand-new tables (bank_accounts, receipts, payments)
    # exist, then migrate the new FK column onto the already-existing
    # ledger_accounts table (create_all never alters existing tables).
    Base.metadata.create_all(engine)
    _migrate_add_column("ledger_accounts", "bank_account_id", "INTEGER REFERENCES bank_accounts(id)")

    session = SessionLocal()
    try:
        ensure_system_accounts(session)
        ensure_profile(session)
        ensure_roles_and_admin(session)
    finally:
        session.close()


def main():
    initialize_database()
    backend = "SQL Server" if "mssql" in DATABASE_URL else (
        "SQLite" if DATABASE_URL.startswith("sqlite") else "Other"
    )
    print("Database tables created successfully.")
    # Show the target so a fresh setup can be confirmed to have hit MSSQL and
    # not SQLite by mistake. Trim to avoid printing any credentials in full.
    print(f"Connected to: {DATABASE_URL[:50]}...")
    print(f"Backend: {backend}")
    if backend == "SQLite":
        print(f"SQLite file: {DATABASE_PATH}")
    print("Tables:", ", ".join(Base.metadata.tables.keys()))
    print("System ledger accounts ensured")
    print("Company profile ensured")
    print("Roles and default admin ensured")


if __name__ == "__main__":
    main()
