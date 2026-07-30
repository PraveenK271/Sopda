"""Database connection and session setup.

Backend is configurable (Phase 4). The app reads ``GEMINI_DB_URL`` from a
``.env`` file (or the environment); if it is not set it falls back to the
local SQLite file, so development and packaged single-user builds are
unchanged. Because everything goes through SQLAlchemy, switching to Microsoft
SQL Server is exactly this connection-string change — no model or service code
changes.
"""

import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def get_app_root() -> str:
    """Root directory for user data (db, documents, .env), source or packaged.

    PyInstaller extracts the read-only bundle to a temp dir (``sys._MEIPASS``)
    that is wiped on exit, so user data must NOT live there. When frozen we use
    the folder containing the .exe (stable, writable); from source we use this
    package's own directory (``gemini_erp/``) so the dev layout is unchanged.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_app_root()

# Load .env from the app root first (works when the app is launched from any
# working directory, source or packaged), then fall back to a default search.
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv()

# SQLite path is still derived from the app root so a fallback / dev run keeps
# the db next to the code (or the .exe when frozen), never in the temp bundle.
DATABASE_PATH = os.path.join(BASE_DIR, "gemini_erp.db")
_SQLITE_URL = f"sqlite:///{DATABASE_PATH}"

# GEMINI_DB_URL from .env wins; otherwise SQLite. One code path, two backends.
DATABASE_URL = os.getenv("GEMINI_DB_URL", _SQLITE_URL)

# check_same_thread is a SQLite-only pragma (Qt touches the session from worker
# threads). SQL Server / other backends must NOT receive it.
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
else:
    _connect_args = {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_session():
    """Return a new SQLAlchemy session."""
    return SessionLocal()
