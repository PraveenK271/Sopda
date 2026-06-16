"""Database connection and session setup.

SQLite for now (Phase 1). Because we use SQLAlchemy, switching to
Microsoft SQL Server later (Phase 4) is mostly a connection-string change.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "gemini_erp.db")
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_session():
    """Return a new SQLAlchemy session."""
    return SessionLocal()
