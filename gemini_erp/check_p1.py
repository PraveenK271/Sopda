"""Patch v1.1.0 P1 check: the migration framework.

Asserts:
- on a fresh database every migration applies and is recorded in schema_migrations
- running run_pending() a second time applies nothing and raises nothing
- column_exists() is right for a known and an unknown column
- a deliberately failing migration is NOT recorded, its partial DDL is rolled
  back (real transactional DDL on SQLite), and the run stops there — a later
  migration in the same run is not applied
- the automatic pre-migration backup is written (and named pre_patch_...)

ALWAYS runs on a throwaway SQLite file: GEMINI_DB_URL is overridden below,
before database.py is imported, so a .env pointing at a live SQL Server is
never touched.

Run with: python check_p1.py
"""

import os
import tempfile

_DB_FILE = os.path.join(tempfile.mkdtemp(prefix="gemini_check_p1_"), "check_p1.db")
os.environ["GEMINI_DB_URL"] = f"sqlite:///{_DB_FILE}"

import types  # noqa: E402

from sqlalchemy import inspect  # noqa: E402

from create_db import initialize_database  # noqa: E402
from database import engine, get_session  # noqa: E402
from models import SchemaMigration  # noqa: E402
from services.backup_service import BackupService  # noqa: E402
from services.migration_service import MigrationError, MigrationService  # noqa: E402


def _fake_migration(version, fail):
    """An in-memory migration module. The failing one adds a column FIRST and
    then raises, so we can prove the ALTER itself was rolled back."""

    def upgrade(connection, dialect_name):
        MigrationService.add_column_if_missing(
            connection, dialect_name, "items", f"chk_col_{version}",
            f"chk_col_{version} INTEGER NOT NULL DEFAULT 0",
            f"chk_col_{version} INT NOT NULL DEFAULT 0",
        )
        if fail:
            raise RuntimeError("deliberate failure for check_p1")

    module = types.ModuleType(f"fake_m{version}")
    module.VERSION = version
    module.DESCRIPTION = f"check_p1 fake migration {version}"
    module.upgrade = upgrade
    return module


def _recorded_versions() -> set[str]:
    session = get_session()
    try:
        return {v for (v,) in session.query(SchemaMigration.version)}
    finally:
        session.close()


def main():
    assert "check_p1" in str(engine.url), f"refusing to run on {engine.url}"
    initialize_database()
    service = MigrationService()
    expected = [m.VERSION for m in service.discover_migrations()]
    assert expected == sorted(expected) and expected[:3] == ["001", "002", "003"], expected

    # [1] fresh database: all apply and are recorded
    session = get_session()
    try:
        pending = [m.VERSION for m in service.get_pending_migrations(session)]
        assert pending == expected, pending
        applied = service.run_pending(session, applied_by="check_p1")
    finally:
        session.close()
    assert applied == expected, applied
    assert _recorded_versions() == set(expected)
    print(f"[1] fresh database: applied and recorded {applied} OK")

    # [2] second run is a harmless no-op
    session = get_session()
    try:
        assert service.get_pending_migrations(session) == []
        assert service.run_pending(session, applied_by="check_p1") == []
    finally:
        session.close()
    assert _recorded_versions() == set(expected)
    print("[2] second run applies nothing, raises nothing OK")

    # [2b] each migration's upgrade() is itself idempotent (re-run directly)
    with engine.begin() as conn:
        for module in service.discover_migrations():
            module.upgrade(conn, engine.dialect.name)
    print("[2b] re-running every upgrade() directly on a migrated db is a no-op OK")

    # [3] column_exists / table_exists
    with engine.connect() as conn:
        assert MigrationService.column_exists(conn, "purchase_invoices", "special_discount")
        assert MigrationService.column_exists(conn, "purchase_invoices", "total")
        assert not MigrationService.column_exists(conn, "purchase_invoices", "no_such_column")
        assert MigrationService.table_exists(conn, "supplier_credit_notes")
        assert not MigrationService.table_exists(conn, "no_such_table")
    print("[3] column_exists / table_exists correct for known and unknown names OK")

    # [4] a failing migration: rolled back, not recorded, run stops
    failing = _fake_migration("900", fail=True)
    after = _fake_migration("901", fail=False)
    session = get_session()
    try:
        try:
            service.run_pending(session, applied_by="check_p1", migrations=[after, failing])
            raise AssertionError("a failing migration must raise")
        except MigrationError as exc:
            assert exc.version == "900", exc.version
            assert "900" in str(exc)
            assert exc.applied == [], exc.applied
    finally:
        session.close()
    recorded = _recorded_versions()
    assert "900" not in recorded, "failed migration must not be recorded"
    assert "901" not in recorded, "run must stop at the first failure"
    cols = [c["name"] for c in inspect(engine).get_columns("items")]
    assert "chk_col_900" not in cols, "the failed migration's ALTER must be rolled back"
    assert "chk_col_901" not in cols, "a migration after the failure must not run"
    print("[4] failing migration 900: raised naming 900, not recorded, its ALTER rolled "
          "back, and 901 never ran OK")

    # [5] pre-migration backup
    path = BackupService().auto_backup_before_migration("1.1.0")
    try:
        assert os.path.basename(path).startswith("pre_patch_1.1.0_"), path
        assert os.path.getsize(path) > 0
        print(f"[5] pre-migration backup written: {os.path.basename(path)} OK")
    finally:
        os.remove(path)  # don't leave test backups in the app's backups/ folder

    print("\nAll P1 (migration framework) checks passed.")


if __name__ == "__main__":
    main()
