"""Authentication and authorization (Service Layer — no auth logic in the UI).

SECURITY (non-negotiable):
- Passwords are NEVER stored or logged in plaintext; only bcrypt hashes exist.
- Hashing/verification goes through passlib's CryptContext (bcrypt). No
  hand-rolled or fast (MD5/SHA) hashing anywhere.
- Password checks use pwd_context.verify() (timing-safe), never ==.
- authenticate() returns None for BOTH unknown-user and wrong-password so a
  caller can't tell whether a username exists.
"""

import json
import logging
from datetime import datetime

import passlib.handlers.bcrypt  # noqa: F401 — needed so PyInstaller bundles this into the .exe
from passlib.context import CryptContext
from sqlalchemy import false, true
from sqlalchemy.orm import Session, joinedload

from models import Role, User
from services.permissions import ROLE_PERMISSIONS

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8

# Default admin seeded on an empty users table (forced to change on first login).
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "Admin@1234"


class AuthService:
    """User creation, login, password changes, and permission checks."""

    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    # --- password hashing -------------------------------------------------

    def hash_password(self, plain: str) -> str:
        """Return the bcrypt hash of a plaintext password."""
        return self._pwd_context.hash(plain)

    # --- user management --------------------------------------------------

    def create_user(
        self,
        session: Session,
        username: str,
        plain_password: str,
        full_name: str | None,
        role_id: int,
        must_change_password: bool = False,
        created_by: str | None = None,
    ) -> User:
        """Create a user with a hashed password. One transaction.

        Raises ValueError for a duplicate username or a too-short password
        (messages are safe to show in the UI — they never contain the password).
        """
        username = (username or "").strip()
        if not username:
            raise ValueError("Username is required")
        if len(plain_password or "") < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

        existing = (
            session.query(User)
            .filter(User.username == username, User.is_deleted == false())
            .first()
        )
        if existing is not None:
            raise ValueError(f"Username '{username}' already exists")

        try:
            user = User(
                username=username,
                password_hash=self.hash_password(plain_password),
                full_name=full_name,
                role_id=role_id,
                is_active=True,
                must_change_password=must_change_password,
                created_by=created_by,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            logger.info("Created user %s (role_id=%s)", user.username, role_id)
            return user
        except Exception:
            session.rollback()
            logger.exception("Failed to create user %s", username)
            raise

    def authenticate(self, session: Session, username: str, plain_password: str) -> User | None:
        """Return the User on a correct login, else None.

        None is returned identically for an unknown username and a wrong
        password (no user-enumeration leak). Updates last_login on success. The
        returned User is detached with its role eagerly loaded, so the caller can
        read username/role/permissions after the session closes.
        """
        user = (
            session.query(User)
            .options(joinedload(User.role))
            .filter(
                User.username == (username or "").strip(),
                User.is_active == true(),
                User.is_deleted == false(),
            )
            .first()
        )
        if user is None:
            return None
        if not self._pwd_context.verify(plain_password or "", user.password_hash):
            return None

        user.last_login = datetime.utcnow()
        session.commit()
        # Re-populate after the commit expired the instance, force the role +
        # permissions to load, then detach a stable copy for SessionContext.
        session.refresh(user)
        _ = user.role.permissions
        session.expunge(user)
        logger.info("User %s authenticated", user.username)
        return user

    def change_password(
        self, session: Session, user_id: int, old_plain: str, new_plain: str
    ) -> bool:
        """Change a user's own password after verifying the old one.

        Returns False if the old password does not match. Raises ValueError if
        the new password is too short. Clears must_change_password on success.
        """
        user = session.get(User, user_id)
        if user is None:
            return False
        if not self._pwd_context.verify(old_plain or "", user.password_hash):
            return False
        if len(new_plain or "") < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        try:
            user.password_hash = self.hash_password(new_plain)
            user.must_change_password = False
            user.modified_by = user.username
            session.commit()
            logger.info("Password changed for user %s", user.username)
            return True
        except Exception:
            session.rollback()
            logger.exception("Failed to change password for user id %s", user_id)
            raise

    def admin_reset_password(
        self, session: Session, user_id: int, new_plain: str, created_by: str | None
    ) -> None:
        """Administrator resets another user's password (no old password needed).

        Forces must_change_password=True so the user must set their own on the
        next login.
        """
        if len(new_plain or "") < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        user = session.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        try:
            user.password_hash = self.hash_password(new_plain)
            user.must_change_password = True
            user.modified_by = created_by
            session.commit()
            logger.info("Password reset by admin for user %s", user.username)
        except Exception:
            session.rollback()
            logger.exception("Failed to reset password for user id %s", user_id)
            raise

    def list_users(self, session: Session) -> list[User]:
        """All non-deleted users with their role eagerly loaded, ordered by name."""
        return (
            session.query(User)
            .options(joinedload(User.role))
            .filter(User.is_deleted == false())
            .order_by(User.username)
            .all()
        )

    def deactivate_user(self, session: Session, user_id: int, created_by: str | None) -> None:
        """Deactivate (never physically delete — the name lives on in created_by)."""
        user = session.get(User, user_id)
        if user is None:
            raise ValueError(f"User {user_id} not found")
        try:
            user.is_active = False
            user.modified_by = created_by
            session.commit()
            logger.info("Deactivated user %s", user.username)
        except Exception:
            session.rollback()
            logger.exception("Failed to deactivate user id %s", user_id)
            raise

    # --- authorization ----------------------------------------------------

    @staticmethod
    def has_permission(user: User | None, module_key: str) -> bool:
        """True if the (active) user's role permits module_key."""
        if user is None or not user.is_active:
            return False
        try:
            permitted = json.loads(user.role.permissions)
        except (ValueError, TypeError):
            logger.warning("Role %s has unreadable permissions", getattr(user, "role_id", "?"))
            return False
        return module_key in permitted


def ensure_roles_and_admin(session: Session) -> None:
    """Seed the four roles and a default admin. Idempotent (like ensure_system_accounts).

    - Creates any missing role with its permission list.
    - If the users table is empty, creates the default admin (must change the
      password on first login). If ANY user already exists, does nothing — an
      established admin is never overwritten or reset.
    Commits on the passed-in session.
    """
    try:
        # Role permission sets are code-defined (permissions.py is the single
        # source of truth). Create missing roles AND reconcile existing ones so
        # that adding a new module key (e.g. data_import) takes effect on upgrade
        # without a manual DB edit.
        existing_roles = {r.name: r for r in session.query(Role).all()}
        for role_name, permissions in ROLE_PERMISSIONS.items():
            desired = json.dumps(permissions)
            role = existing_roles.get(role_name)
            if role is None:
                session.add(Role(name=role_name, permissions=desired))
                logger.info("Created role %s", role_name)
            elif role.permissions != desired:
                role.permissions = desired
                logger.info("Updated permissions for role %s", role_name)
        session.commit()

        user_count = session.query(User).count()
        if user_count == 0:
            from services.permissions import ROLE_ADMINISTRATOR

            admin_role = session.query(Role).filter(Role.name == ROLE_ADMINISTRATOR).one()
            admin = User(
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=AuthService().hash_password(DEFAULT_ADMIN_PASSWORD),
                full_name="Administrator",
                role_id=admin_role.id,
                is_active=True,
                must_change_password=True,
            )
            session.add(admin)
            session.commit()
            # The spec requires surfacing the default credential once so the
            # operator knows how to log in the very first time; the account is
            # forced to change it immediately.
            print(
                f"Default admin created ({DEFAULT_ADMIN_USERNAME} / {DEFAULT_ADMIN_PASSWORD}). "
                "You will be required to change this password on first login."
            )
    except Exception:
        session.rollback()
        logger.exception("Failed to ensure roles and admin")
        raise
