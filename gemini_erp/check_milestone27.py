"""Milestone 27 check (headless): RBAC permission sets, created_by wiring,
SessionContext default, and admin password reset.

Asserts:
- each of the 4 seeded roles yields exactly its permitted module set
  (has_permission for every module key)
- a sales invoice created while a user is in SessionContext stores that
  username in created_by (not None, not "system")
- SessionContext.get_username() is "system" when nobody is logged in
- admin_reset_password sets must_change_password = True

The UI (login/tabs/logout) is verified manually — see the checklist.

Run with: python check_milestone27.py
"""

from datetime import date, datetime

from database import get_session
from models import Role, SalesInvoice
from services.auth_service import AuthService, ensure_roles_and_admin
from services.customer_service import CustomerService
from services.item_service import ItemService
from services.permissions import ALL_MODULES, ROLE_PERMISSIONS
from services.sales_service import SalesService
from services.session_context import SessionContext


def main():
    auth = AuthService()
    session = get_session()
    try:
        ensure_roles_and_admin(session)
        role_id = {name: rid for (name, rid) in session.query(Role.name, Role.id)}
        stamp = datetime.now().strftime("%H%M%S%f")

        # 1. Each role yields exactly its permitted module set.
        for role_name, expected in ROLE_PERMISSIONS.items():
            user = auth.create_user(
                session, f"chk_m27_{role_name.replace(' ', '')}_{stamp}", "RolePwd@123",
                f"{role_name} Test", role_id[role_name],
            )
            session.refresh(user)
            for module in ALL_MODULES:
                got = auth.has_permission(user, module)
                want = module in expected
                assert got == want, f"{role_name}: {module} expected {want}, got {got}"
            auth.deactivate_user(session, user.id, created_by="check_milestone27")
        print("RBAC: all 4 roles map to exactly their permitted modules")

        # 2. created_by wiring — a sale created with a user in SessionContext
        #    stores that user's username.
        actor = auth.create_user(
            session, f"chk_m27_actor_{stamp}", "ActorPwd@123", "Actor",
            role_id["Sales User"],
        )
        session.refresh(actor)
        SessionContext.set_user(actor)

        item = ItemService().add_item(
            code=f"CHK-M27-ITEM-{stamp}", name="M27 Item", unit="PCS",
            gst_rate=18, opening_stock=100, created_by=SessionContext.get_username(),
        )
        customer = CustomerService().add_customer(
            name=f"CHK-M27 Customer {stamp}", gstin="37AAAAA0000A1Z5",
            state="Andhra Pradesh", address="Test",
            created_by=SessionContext.get_username(),
        )
        invoice_no = f"CHK-M27-INV-{stamp}"
        SalesService().create_invoice(
            invoice_no=invoice_no,
            invoice_date=date.today(),
            customer_id=customer.id,
            lines=[{"item_id": item.id, "quantity": 1, "rate": 100}],
            created_by=SessionContext.get_username(),  # what the UI passes
        )
        saved = session.query(SalesInvoice).filter(SalesInvoice.invoice_no == invoice_no).one()
        assert saved.created_by == actor.username, f"created_by={saved.created_by!r}"
        assert saved.created_by not in (None, "system"), "created_by not wired to the user"
        print(f"created_by wired: invoice {invoice_no} created_by={saved.created_by}")

        # 3. SessionContext default is 'system' with nobody logged in.
        SessionContext.clear()
        assert SessionContext.get_username() == "system", "expected 'system' when logged out"
        print("SessionContext.get_username() == 'system' when logged out")

        # 4. admin_reset_password forces a password change.
        auth.admin_reset_password(session, actor.id, "ResetPwd@123", created_by="admin")
        session.refresh(actor)
        assert actor.must_change_password is True, "reset did not force password change"
        print("admin_reset_password sets must_change_password = True")

        auth.deactivate_user(session, actor.id, created_by="check_milestone27")
        print("PASS")
    finally:
        session.close()


if __name__ == "__main__":
    main()
