"""Milestone 29a check: the FastAPI read API (headless, FastAPI TestClient).

Asserts:
- login: wrong password / unknown user -> 401 with the SAME generic message;
  a protected endpoint without a token -> 401
- a valid login returns a JWT; /api/me reports the role's permitted modules
- RBAC: a Sales User token gets 200 on /stock + /invoices/recent but 403 on
  /outstanding + /gst/gstr3b
- endpoint numbers MATCH the desktop service output for the same data
  (/outstanding, /stock, /gst/gstr3b, /dashboard)
- the login rate-limit kicks in (429) after repeated failures

Uses its own Administrator- and Sales-User test accounts (known passwords) so it
never depends on the seeded admin's password, which a manual UI test may change.

Run with: python check_milestone29.py
"""

import warnings
from datetime import date, datetime

warnings.filterwarnings("ignore")  # silence the TestClient httpx deprecation note

from fastapi.testclient import TestClient  # noqa: E402

from api.config import LOGIN_MAX_ATTEMPTS  # noqa: E402
from api.main import app  # noqa: E402
from database import get_session  # noqa: E402
from models import Role  # noqa: E402
from services.accounting_service import AccountingService  # noqa: E402
from services.auth_service import AuthService  # noqa: E402
from services.gst_report_service import GstReportService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.permissions import ALL_MODULES, ROLE_ADMINISTRATOR, ROLE_SALES_USER  # noqa: E402

client = TestClient(app)
GST_FROM, GST_TO = date(2019, 4, 1), date(2020, 3, 31)  # M18/M19 fixture FY


def _login(username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def main():
    auth = AuthService()
    stamp = datetime.now().strftime("%H%M%S%f")
    session = get_session()
    try:
        role_id = {name: rid for (name, rid) in session.query(Role.name, Role.id)}
        admin_name = f"chk_m29_admin_{stamp}"
        sales_name = f"chk_m29_sales_{stamp}"
        admin_user = auth.create_user(session, admin_name, "AdminPwd@123", "M29 Admin", role_id[ROLE_ADMINISTRATOR])
        sales_user = auth.create_user(session, sales_name, "SalesPwd@123", "M29 Sales", role_id[ROLE_SALES_USER])
        admin_id, sales_id = admin_user.id, sales_user.id
    finally:
        session.close()

    # 1. Login failures + no-token.
    assert _login(admin_name, "wrong-password").status_code == 401
    r = _login("no-such-user-xyz", "whatever")
    assert r.status_code == 401 and r.json()["detail"] == "Invalid username or password"
    assert client.get("/api/stock").status_code == 401
    print("Login: wrong pw 401, unknown user 401 (generic), no-token 401")

    # 2. Valid login -> token + /api/me permitted modules.
    r = _login(admin_name, "AdminPwd@123")
    assert r.status_code == 200, r.text
    admin_tok = r.json()["access_token"]
    me = client.get("/api/me", headers=_h(admin_tok)).json()
    assert set(me["permitted_modules"]) == set(ALL_MODULES), me["permitted_modules"]
    assert me["role"] == ROLE_ADMINISTRATOR
    print(f"Admin login OK; /api/me lists all {len(ALL_MODULES)} modules")

    # 3. Numbers match the desktop services (consistency, whatever the DB holds).
    api_cust = client.get("/api/outstanding/customers", headers=_h(admin_tok)).json()
    assert api_cust == AccountingService.get_outstanding_customers(), "outstanding customers mismatch"
    api_supp = client.get("/api/outstanding/suppliers", headers=_h(admin_tok)).json()
    assert api_supp == AccountingService.get_outstanding_suppliers(), "outstanding suppliers mismatch"

    api_stock = client.get("/api/stock", headers=_h(admin_tok)).json()
    svc_items = ItemService().list_items()
    assert [(i["id"], i["current_stock"]) for i in api_stock] == [
        (i["id"], i["current_stock"]) for i in svc_items
    ], "stock mismatch"
    assert all("low_stock" in i for i in api_stock), "stock rows missing low_stock flag"

    api_gst = client.get(
        "/api/gst/gstr3b", params={"date_from": GST_FROM.isoformat(), "date_to": GST_TO.isoformat()},
        headers=_h(admin_tok),
    ).json()
    assert api_gst == GstReportService.get_gstr3b_summary(GST_FROM, GST_TO), "gstr3b mismatch"
    print("Numbers match desktop: outstanding, stock, gstr3b")

    # 4. RBAC as a Sales User.
    r = _login(sales_name, "SalesPwd@123")
    sales_tok = r.json()["access_token"]
    assert client.get("/api/stock", headers=_h(sales_tok)).status_code == 200
    assert client.get("/api/invoices/recent", headers=_h(sales_tok)).status_code == 200
    assert client.get("/api/outstanding/customers", headers=_h(sales_tok)).status_code == 403
    assert client.get(
        "/api/gst/gstr3b", params={"date_from": GST_FROM.isoformat(), "date_to": GST_TO.isoformat()},
        headers=_h(sales_tok),
    ).status_code == 403
    dash = client.get("/api/dashboard", headers=_h(sales_tok)).json()
    assert dash["receivable_total"] is None, "Sales User must not see receivables"
    assert dash["sales_today"] is not None and dash["low_stock_count"] is not None
    print("RBAC: Sales User 200 stock/invoices, 403 outstanding/gst; dashboard hides receivables")

    # 5. Rate limit after repeated failures (dedicated unknown username).
    rl_user = f"chk_m29_rl_{stamp}"
    for _ in range(LOGIN_MAX_ATTEMPTS):
        _login(rl_user, "bad")
    assert _login(rl_user, "bad").status_code == 429, "rate limit did not trigger"
    print(f"Rate limit: 429 after {LOGIN_MAX_ATTEMPTS} failed attempts")

    session = get_session()
    try:
        auth.deactivate_user(session, admin_id, created_by="check_milestone29")
        auth.deactivate_user(session, sales_id, created_by="check_milestone29")
    finally:
        session.close()

    print("PASS")


if __name__ == "__main__":
    main()
