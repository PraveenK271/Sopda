"""Milestone 26 check: Users, Roles & AuthService.

Asserts idempotent seeding, the default admin, password hashing (never
plaintext), authenticate() success/failure (same None for unknown-user and
wrong-password), create_user validation, change_password, and per-role
has_permission.

Uses a unique per-run test username so it is repeatable (username has a UNIQUE
constraint, so a soft-deleted one can't be reused). Never touches the real
admin's password.

Run with: python check_milestone26.py
"""

from datetime import datetime

from database import get_session
from models import Role, User
from services.auth_service import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    AuthService,
    ensure_roles_and_admin,
)
from services.permissions import (
    ALL_MODULES,
    MODULE_ACCOUNTS,
    MODULE_BILLING,
    MODULE_GST,
    MODULE_ITEMS,
    ROLE_ACCOUNTANT,
    ROLE_ADMINISTRATOR,
    ROLE_INVENTORY_MANAGER,
    ROLE_PERMISSIONS,
    ROLE_SALES_USER,
)


def main():
    auth = AuthService()
    session = get_session()
    try:
        # 1. Idempotent seeding — running twice makes no duplicate roles/admins.
        ensure_roles_and_admin(session)
        ensure_roles_and_admin(session)
        role_count = session.query(Role).count()
        assert role_count == len(ROLE_PERMISSIONS), f"expected {len(ROLE_PERMISSIONS)} roles, got {role_count}"
        admin_count = session.query(User).filter(User.username == DEFAULT_ADMIN_USERNAME).count()
        assert admin_count == 1, f"expected exactly one admin, got {admin_count}"
        print(f"Idempotent: {role_count} roles, {admin_count} admin")

        # 2. Default admin exists and must change password.
        admin = session.query(User).filter(User.username == DEFAULT_ADMIN_USERNAME).one()
        assert admin.must_change_password is True, "default admin should require a password change"

        # 3. Stored hash is not the plaintext.
        assert admin.password_hash != DEFAULT_ADMIN_PASSWORD, "password stored in plaintext!"
        print("Default admin present, must_change_password=True, hash != plaintext")

        # 4-6. authenticate: right pw -> User; wrong pw -> None; unknown -> None.
        ok = auth.authenticate(session, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)
        assert ok is not None and ok.username == DEFAULT_ADMIN_USERNAME, "correct login failed"
        assert auth.authenticate(session, DEFAULT_ADMIN_USERNAME, "wrong-password") is None, "wrong pw not rejected"
        assert auth.authenticate(session, "no-such-user-xyz", "whatever") is None, "unknown user not rejected"
        print("authenticate: correct=User, wrong=None, unknown=None")

        # Role ids for the tests below.
        role_id = {name: rid for (name, rid) in session.query(Role.name, Role.id)}

        # 7-8. create_user validation.
        stamp = datetime.now().strftime("%H%M%S%f")
        uname = f"chk_m26_{stamp}"
        user = auth.create_user(
            session, uname, "Secret@123", "Check M26 User",
            role_id[ROLE_ACCOUNTANT], must_change_password=True,
        )
        assert user.password_hash != "Secret@123", "created user hash is plaintext!"

        try:
            auth.create_user(session, uname, "Another@123", "Dup", role_id[ROLE_ACCOUNTANT])
            raise AssertionError("duplicate username did not raise")
        except ValueError:
            pass
        try:
            auth.create_user(session, f"chk_m26_short_{stamp}", "12345", "Short", role_id[ROLE_ACCOUNTANT])
            raise AssertionError("short password did not raise")
        except ValueError:
            pass
        print("create_user: hashed, duplicate raises, short password raises")

        # 9-10. change_password.
        assert auth.change_password(session, user.id, "wrong-old", "NewSecret@123") is False, "wrong old accepted"
        assert auth.change_password(session, user.id, "Secret@123", "NewSecret@123") is True, "right old failed"
        session.refresh(user)
        assert user.must_change_password is False, "must_change_password not cleared"
        # New password now authenticates; old one does not.
        assert auth.authenticate(session, uname, "NewSecret@123") is not None, "new pw fails to log in"
        assert auth.authenticate(session, uname, "Secret@123") is None, "old pw still works"
        print("change_password: wrong old=False, right old=True, flag cleared, new pw works")

        # 11. has_permission per role.
        def make_user(role_name):
            u = auth.create_user(
                session, f"chk_m26_{role_name.replace(' ', '')}_{stamp}", "RolePwd@123",
                role_name, role_id[role_name],
            )
            session.refresh(u)
            return u

        admin_authed = auth.authenticate(session, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD)
        for module in ALL_MODULES:
            assert auth.has_permission(admin_authed, module), f"admin missing {module}"

        sales_user = make_user(ROLE_SALES_USER)
        assert auth.has_permission(sales_user, MODULE_BILLING), "Sales User should have billing"
        assert not auth.has_permission(sales_user, MODULE_ACCOUNTS), "Sales User should NOT have accounts"

        inv_user = make_user(ROLE_INVENTORY_MANAGER)
        assert auth.has_permission(inv_user, MODULE_ITEMS), "Inventory Manager should have items"
        assert not auth.has_permission(inv_user, MODULE_GST), "Inventory Manager should NOT have gst"

        assert auth.has_permission(None, MODULE_BILLING) is False, "None user should have no permission"
        print("has_permission: Administrator=all, Sales User billing-not-accounts, Inventory items-not-gst")

        # Housekeeping: these check users are inactive fixtures, not real logins.
        for u in (user, sales_user, inv_user):
            auth.deactivate_user(session, u.id, created_by="check_milestone26")

        print("PASS")
    finally:
        session.close()


if __name__ == "__main__":
    main()
