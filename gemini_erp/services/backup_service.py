"""Create database backups (Settings -> "Backup now").

Backend-aware, like the rest of Phase 4:
- **SQLite** (dev / single-user): copy the database file to a timestamped copy.
- **SQL Server**: run ``BACKUP DATABASE`` to a ``.bak`` on the server. The file
  is written by the SQL Server *service* (not this app), so it lands on the
  server's filesystem — for a local Express instance that is the same machine.
  We default to the instance's own default backup directory, which the service
  account can always write to.

Restore is intentionally NOT automated here: a SQLite restore just means copying
a backup file back while the app is closed, and a SQL Server restore needs
exclusive database access and is safest done from SSMS or a scheduled job. For
daily backups, schedule this (SQLite) or a SQL Server Agent job (MSSQL) — see
the README.
"""

import logging
import os
import shutil
from datetime import datetime

from database import DATABASE_URL, engine, get_app_root

logger = logging.getLogger(__name__)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _default_backup_dir() -> str:
    """App-local backups folder (used for SQLite, and as an MSSQL fallback)."""
    path = os.path.join(get_app_root(), "backups")
    os.makedirs(path, exist_ok=True)
    return path


class BackupService:
    """Produce a database backup artifact for the current backend."""

    def is_sqlite(self) -> bool:
        return DATABASE_URL.startswith("sqlite")

    def backup(self, dest_dir: str | None = None) -> str:
        """Create a backup and return the full path to the artifact.

        For SQLite the artifact is on this machine. For SQL Server it is on the
        server machine (same machine for a local instance); ``dest_dir``, when
        given for MSSQL, must be a path the SQL Server service account can write.
        """
        if self.is_sqlite():
            return self._backup_sqlite(dest_dir)
        return self._backup_mssql(dest_dir)

    def _backup_sqlite(self, dest_dir: str | None) -> str:
        dest_dir = dest_dir or _default_backup_dir()
        os.makedirs(dest_dir, exist_ok=True)
        # Back up the file the engine actually uses (from the connection URL),
        # not a hardcoded path — so a GEMINI_DB_URL override is honoured too.
        source = engine.url.database
        name = f"gemini_erp_backup_{_timestamp()}.db"
        dest = os.path.join(dest_dir, name)
        # copy2 preserves metadata; SQLite is a single file so this is a complete
        # snapshot as long as no write is mid-flight (fine for a manual backup).
        shutil.copy2(source, dest)
        logger.info("SQLite backup of %s written to %s", source, dest)
        return dest

    def _backup_mssql(self, dest_dir: str | None) -> str:
        db_name = engine.url.database
        if not db_name:
            raise RuntimeError("Cannot determine database name for SQL Server backup")

        # BACKUP is a non-standard T-SQL command that streams progress result
        # sets and must not run in a transaction. Drive the raw pyodbc cursor
        # directly (autocommit on), consuming every result set so the command
        # actually completes — going through the SQLAlchemy execution layer
        # silently no-ops it. Restore autocommit before returning the pooled
        # connection so we don't leak the setting.
        raw = engine.raw_connection()
        try:
            dbapi_conn = raw.driver_connection
            previous_autocommit = dbapi_conn.autocommit
            dbapi_conn.autocommit = True
            try:
                cursor = dbapi_conn.cursor()
                if dest_dir is None:
                    # The instance's own backup folder: always writable by the SQL
                    # Server service account (a client-chosen folder usually is
                    # not). NULL on very old servers -> app-local fallback.
                    dest_dir = (
                        cursor.execute(
                            "SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') "
                            "AS NVARCHAR(4000))"
                        ).fetchval()
                        or _default_backup_dir()
                    )

                filename = f"{db_name}_backup_{_timestamp()}.bak"
                dest = os.path.join(dest_dir, filename)

                # INIT + FORMAT overwrite/create a fresh media set (no COMPRESSION:
                # SQL Server Express does not support backup compression).
                self._run_to_completion(
                    cursor, f"BACKUP DATABASE [{db_name}] TO DISK = N'{dest}' WITH INIT, FORMAT"
                )
                # The .bak lands on the SERVER's filesystem (same machine for a
                # local instance) in a folder the client may not be able to read,
                # so we cannot os.path.exists it. VERIFYONLY confirms server-side
                # that a valid, restorable backup set was written; it raises if
                # the backup silently failed.
                self._run_to_completion(cursor, f"RESTORE VERIFYONLY FROM DISK = N'{dest}'")
                cursor.close()
            finally:
                dbapi_conn.autocommit = previous_autocommit
        finally:
            raw.close()
        logger.info("SQL Server backup of %s written (server-side) to %s", db_name, dest)
        return dest

    @staticmethod
    def _run_to_completion(cursor, sql: str) -> None:
        """Execute a T-SQL command that emits progress result sets, to the end."""
        cursor.execute(sql)
        while cursor.nextset():
            pass
