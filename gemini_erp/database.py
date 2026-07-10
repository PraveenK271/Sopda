"""Database connection and session setup.

SQLite for now (Phase 1). Because we use SQLAlchemy, switching to
Microsoft SQL Server later (Phase 4) is mostly a connection-string change.
"""

import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def get_app_root() -> str:
    """Root directory for user data (db, documents), source or packaged.

    PyInstaller extracts the read-only bundle to a temp dir (``sys._MEIPASS``)
    that is wiped on exit, so user data must NOT live there. When frozen we use
    the folder containing the .exe (stable, writable); from source we use this
    package's own directory (``gemini_erp/``) so the dev layout is unchanged.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = get_app_root()
DATABASE_PATH = os.path.join(BASE_DIR, "gemini_erp.db")
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_session():
    """Return a new SQLAlchemy session."""
    return SessionLocal()
