"""Numbered, additive-only schema migrations for patching a LIVE database.

Why this exists: ``Base.metadata.create_all()`` creates missing TABLES but never
adds missing COLUMNS to tables that already exist. On a user's existing
database a new model column without a migration fails at runtime with
"Invalid column name ...". Every schema change from patch v1.1.0 onwards ships
as a numbered module in ``migrations/`` and is applied here on startup.

Hand-rolled rather than Alembic on purpose (INSTRUCTIONS_PATCH_V1_1.md, P1): the
rule is ADDITIVE ONLY (add a column / add a table — never drop, rename, retype
or delete), so a small runner that works identically on SQLite and SQL Server
is enough, and every line of it can be read.

Guarantees:
- each pending migration runs in its OWN transaction, and its
  ``schema_migrations`` row is written in that same transaction — so a failed
  migration is rolled back and never recorded;
- the run stops at the first failure (later migrations may depend on it);
- migrations are idempotent (they check before acting), so re-running is safe.
"""

import importlib
import logging
from datetime import datetime

from sqlalchemy import create_engine, event, false, inspect

from database import engine as app_engine
from models import SchemaMigration

logger = logging.getLogger(__name__)


class MigrationError(RuntimeError):
    """A migration failed. ``version`` names it; ``applied`` lists the versions
    that DID apply (and were committed) before it."""

    def __init__(self, version: str, message: str, applied: list[str]):
        super().__init__(f"Database migration {version} failed: {message}")
        self.version = version
        self.applied = applied


class MigrationService:
    """Find, order and apply pending migrations; small schema helpers."""

    def __init__(self, engine=None):
        self._engine = engine or app_engine

    # ----- discovery -----------------------------------------------------

    @staticmethod
    def discover_migrations() -> list:
        """Import every module named in ``migrations.MIGRATION_MODULES``.

        Imported by name (not by scanning the folder) so the order is explicit
        and the frozen build works — PyInstaller cannot see these imports, which
        is why the .spec lists each one in ``hiddenimports``.
        """
        import migrations

        return [importlib.import_module(f"migrations.{name}") for name in migrations.MIGRATION_MODULES]

    def _ensure_tracking_table(self) -> None:
        # A pre-patch database has no schema_migrations table yet. Created only
        # when about to migrate (after the backup), never while just checking.
        SchemaMigration.__table__.create(self._engine, checkfirst=True)

    def has_existing_data(self) -> bool:
        """True if the database already has tables — i.e. an existing install
        whose data must be backed up before patching. A brand-new database has
        nothing to back up."""
        with self._engine.connect() as connection:
            return bool(inspect(connection).get_table_names())

    def get_applied_versions(self, session) -> set[str]:
        """Read-only: a database without the tracking table has applied none."""
        with self._engine.connect() as connection:
            if not self.table_exists(connection, SchemaMigration.__tablename__):
                return set()
        return {
            version
            for (version,) in session.query(SchemaMigration.version).filter(
                SchemaMigration.is_deleted == false()
            )
        }

    def get_pending_migrations(self, session, migrations: list | None = None) -> list:
        """Migrations not yet recorded, sorted by VERSION ("001" < "002" ...)."""
        applied = self.get_applied_versions(session)
        candidates = migrations if migrations is not None else self.discover_migrations()
        return sorted(
            (m for m in candidates if m.VERSION not in applied),
            key=lambda m: m.VERSION,
        )

    # ----- running -------------------------------------------------------

    def run_pending(self, session, applied_by: str | None, migrations: list | None = None) -> list[str]:
        """Apply every pending migration in order; return the versions applied.

        Raises MigrationError naming the failing version, after rolling that one
        back. Earlier migrations in the same run stay applied and recorded (each
        committed on its own), which is safe because each is independent and
        idempotent — fixing the cause and re-running continues from the failure.

        ``migrations`` overrides discovery (used by check_p1.py to inject a
        deliberately failing migration).
        """
        pending = self.get_pending_migrations(session, migrations)
        if not pending:
            return []
        self._ensure_tracking_table()

        applied: list[str] = []
        run_engine, disposable = self._transactional_engine()
        try:
            dialect_name = run_engine.dialect.name
            for module in pending:
                version = module.VERSION
                logger.info("Applying migration %s: %s", version, module.DESCRIPTION)
                try:
                    # begin(): one transaction — the schema change AND its
                    # tracking row commit together or not at all.
                    with run_engine.begin() as connection:
                        module.upgrade(connection, dialect_name)
                        connection.execute(
                            SchemaMigration.__table__.insert().values(
                                version=version,
                                description=module.DESCRIPTION[:255],
                                applied_date=datetime.utcnow(),
                                applied_by=applied_by,
                                created_date=datetime.utcnow(),
                                created_by=applied_by,
                                is_deleted=False,
                            )
                        )
                except Exception as exc:
                    logger.exception("Migration %s failed; stopping", version)
                    raise MigrationError(version, str(exc), applied) from exc
                applied.append(version)
                logger.info("Migration %s applied", version)
        finally:
            if disposable:
                run_engine.dispose()
        return applied

    def _transactional_engine(self):
        """Engine to run migrations on, and whether to dispose it afterwards.

        SQL Server supports transactional DDL natively. Python's sqlite3 driver
        does NOT: by default it only opens a transaction before INSERT/UPDATE/
        DELETE, so an ALTER TABLE runs in autocommit and would survive a
        rollback. For SQLite we therefore use a short-lived engine that takes
        over transaction control and emits BEGIN itself (the recipe from the
        SQLAlchemy pysqlite docs), so a failed migration really rolls back.
        Kept separate from the app engine so the rest of the app is unaffected.
        """
        if self._engine.dialect.name != "sqlite":
            return self._engine, False

        run_engine = create_engine(
            self._engine.url, connect_args={"check_same_thread": False}
        )

        @event.listens_for(run_engine, "connect")
        def _disable_driver_transactions(dbapi_connection, _record):
            dbapi_connection.isolation_level = None

        @event.listens_for(run_engine, "begin")
        def _emit_begin(connection):
            connection.exec_driver_sql("BEGIN")

        return run_engine, True

    # ----- helpers for migration modules ---------------------------------

    @staticmethod
    def table_exists(connection, table_name: str) -> bool:
        return table_name in inspect(connection).get_table_names()

    @staticmethod
    def column_exists(connection, table_name: str, column_name: str) -> bool:
        # A fresh Inspector each call: inspectors cache, and a migration checks
        # again after altering the same table.
        cols = [c["name"] for c in inspect(connection).get_columns(table_name)]
        return column_name in cols

    @staticmethod
    def add_column(
        connection, dialect_name: str, table: str, column_def_sqlite: str, column_def_mssql: str
    ) -> None:
        """ALTER TABLE ... ADD a column, in each backend's own syntax.

        SQLite (and most others) say ``ADD COLUMN``; SQL Server says ``ADD``
        with no COLUMN keyword and has its own type names (e.g. BIT).
        """
        if dialect_name == "mssql":
            sql = f"ALTER TABLE {table} ADD {column_def_mssql}"
        else:
            sql = f"ALTER TABLE {table} ADD COLUMN {column_def_sqlite}"
        connection.exec_driver_sql(sql)
        logger.info("Migration DDL: %s", sql)

    @classmethod
    def add_column_if_missing(
        cls,
        connection,
        dialect_name: str,
        table: str,
        column: str,
        column_def_sqlite: str,
        column_def_mssql: str,
    ) -> bool:
        """Idempotent add_column. Returns True if the column was added.

        A table that does not exist yet is left alone: create_all builds it
        from the model, which already carries the column.
        """
        if not cls.table_exists(connection, table):
            return False
        if cls.column_exists(connection, table, column):
            return False
        cls.add_column(connection, dialect_name, table, column_def_sqlite, column_def_mssql)
        return True
