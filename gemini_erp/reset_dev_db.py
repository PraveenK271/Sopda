"""DEV UTILITY — drop and recreate all tables on the CURRENT backend.

Reads GEMINI_DB_URL (via database.py) so it targets whatever .env points at.
Intended for the disposable development database only: it DELETES ALL DATA.
Use it after a schema/index change (e.g. the Phase 4 MSSQL migration) to
rebuild tables from the models. Never point this at production data.

Run with: python reset_dev_db.py
"""

from database import Base, DATABASE_URL, engine
import models  # noqa: F401  -- registers every table on Base.metadata
from create_db import initialize_database


def main() -> None:
    backend = "SQL Server" if "mssql" in DATABASE_URL else (
        "SQLite" if DATABASE_URL.startswith("sqlite") else "Other"
    )
    print(f"Target backend: {backend}  ({DATABASE_URL[:50]}...)")
    Base.metadata.drop_all(engine)
    print("Dropped all tables.")
    initialize_database()
    print("Recreated all tables + seeded system accounts.")
    print("Tables:", ", ".join(Base.metadata.tables.keys()))


if __name__ == "__main__":
    main()
