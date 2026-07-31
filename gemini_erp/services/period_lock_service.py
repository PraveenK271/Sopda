"""Period locking (historical import H6).

Once history is verified, lock the period so imported records cannot be edited.
The lock is enforced in the transactional services (sales/purchase/banking) via
``check_not_locked`` — NOT in the UI — so the import path and any future API are
covered too.
"""

import logging
from datetime import date as date_type
from datetime import datetime

from sqlalchemy import false, true

from database import get_session
from models import PeriodLock

logger = logging.getLogger(__name__)


class PeriodLockError(ValueError):
    """Raised when a create/modify is blocked by an active period lock."""


class PeriodLockService:
    """Set/clear the period lock and answer 'is this date locked?'."""

    def current_lock(self, session=None) -> PeriodLock | None:
        own = session is None
        s = session or get_session()
        try:
            return (
                s.query(PeriodLock)
                .filter(PeriodLock.is_active == true(), PeriodLock.is_deleted == false())
                .order_by(PeriodLock.locked_upto_date.desc())
                .first()
            )
        finally:
            if own:
                s.close()

    def is_locked(self, check_date: date_type) -> bool:
        lock = self.current_lock()
        return lock is not None and check_date <= lock.locked_upto_date

    def check_not_locked(self, check_date: date_type) -> None:
        """Raise PeriodLockError if check_date falls in a locked period."""
        lock = self.current_lock()
        if lock is not None and check_date <= lock.locked_upto_date:
            raise PeriodLockError(
                f"The period is locked up to {lock.locked_upto_date.strftime('%d-%m-%Y')}. "
                "Records dated on or before that date cannot be created or modified. "
                "Ask an Administrator to unlock."
            )

    def lock(self, upto_date: date_type, locked_by: str | None, reason: str | None = None) -> PeriodLock:
        session = get_session()
        try:
            existing = (
                session.query(PeriodLock)
                .filter(PeriodLock.is_active == true(), PeriodLock.is_deleted == false())
                .first()
            )
            if existing is not None:
                raise ValueError(
                    f"Already locked up to {existing.locked_upto_date.strftime('%d-%m-%Y')}. "
                    "Unlock first to change the lock date."
                )
            lock = PeriodLock(
                locked_upto_date=upto_date, locked_by=locked_by, reason=reason,
                is_active=True, created_by=locked_by,
            )
            session.add(lock)
            session.commit()
            session.refresh(lock)
            session.expunge(lock)
            logger.info("Period locked up to %s by %s", upto_date, locked_by)
            return lock
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def unlock(self, unlocked_by: str | None, reason: str) -> None:
        """Administrator action; a reason is required and recorded on the row."""
        if not reason or not reason.strip():
            raise ValueError("An unlock reason is required.")
        session = get_session()
        try:
            lock = (
                session.query(PeriodLock)
                .filter(PeriodLock.is_active == true(), PeriodLock.is_deleted == false())
                .first()
            )
            if lock is None:
                raise ValueError("There is no active lock to remove.")
            lock.is_active = False
            lock.unlocked_by = unlocked_by
            lock.unlocked_date = datetime.utcnow()
            lock.unlock_reason = reason.strip()
            lock.modified_by = unlocked_by
            session.commit()
            logger.info("Period unlocked by %s: %s", unlocked_by, reason.strip())
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_locks(self) -> list[dict]:
        """Full lock/unlock history (newest first) for the UI."""
        session = get_session()
        try:
            rows = (
                session.query(PeriodLock)
                .filter(PeriodLock.is_deleted == false())
                .order_by(PeriodLock.id.desc())
                .all()
            )
            return [
                {
                    "id": r.id,
                    "locked_upto_date": r.locked_upto_date,
                    "locked_by": r.locked_by,
                    "locked_date": r.locked_date,
                    "reason": r.reason,
                    "is_active": r.is_active,
                    "unlocked_by": r.unlocked_by,
                    "unlock_reason": r.unlock_reason,
                }
                for r in rows
            ]
        finally:
            session.close()
