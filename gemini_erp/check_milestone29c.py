"""Milestone 29c check: approve/reject a scanned bill via the API (the single
mobile write action).

Asserts:
- a documents-permitted user can list documents and APPROVE / REJECT one; the
  sign-off records approval_status + approved_by (the JWT user) + approved_date
- a Sales User (no `documents` permission) is 403 on both list and approve
- approving a missing document -> 404
- the decision is persisted (verified straight from the DB)

Run with: python check_milestone29c.py
"""

import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from database import get_session  # noqa: E402
from models import Document, Role  # noqa: E402
from services.auth_service import AuthService  # noqa: E402
from services.permissions import ROLE_ADMINISTRATOR, ROLE_SALES_USER  # noqa: E402

client = TestClient(app)


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
        admin = auth.create_user(session, f"chk_m29c_admin_{stamp}", "AdminPwd@123", "M29c Admin", role_id[ROLE_ADMINISTRATOR])
        sales = auth.create_user(session, f"chk_m29c_sales_{stamp}", "SalesPwd@123", "M29c Sales", role_id[ROLE_SALES_USER])
        admin_name, admin_id = admin.username, admin.id
        sales_name, sales_id = sales.username, sales.id

        # Two scanned-bill fixtures (inserted directly; no file needed).
        doc_a = Document(
            file_name=f"chk_m29c_a_{stamp}.pdf", file_path="/fixture/a.pdf",
            document_type="PURCHASE_BILL", ocr_status="DONE",
        )
        doc_b = Document(
            file_name=f"chk_m29c_b_{stamp}.pdf", file_path="/fixture/b.pdf",
            document_type="PURCHASE_BILL", ocr_status="DONE",
        )
        session.add_all([doc_a, doc_b])
        session.commit()
        session.refresh(doc_a)
        session.refresh(doc_b)
        doc_a_id, doc_b_id = doc_a.id, doc_b.id
    finally:
        session.close()

    admin_tok = _login(admin_name, "AdminPwd@123").json()["access_token"]
    sales_tok = _login(sales_name, "SalesPwd@123").json()["access_token"]

    # New fixtures start PENDING.
    listed = client.get("/api/documents", headers=_h(admin_tok)).json()
    by_id = {d["id"]: d for d in listed}
    assert by_id[doc_a_id]["approval_status"] == "PENDING", by_id[doc_a_id]
    print("List (documents perm): fixtures present and PENDING")

    # Approve one.
    r = client.post(
        f"/api/documents/{doc_a_id}/approve", headers=_h(admin_tok), json={"note": "Looks correct"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approval_status"] == "APPROVED", body
    assert body["approved_by"] == admin_name, body
    assert body["approved_date"] is not None and body["approval_note"] == "Looks correct"
    print(f"Approve: doc {doc_a_id} -> APPROVED by {body['approved_by']}")

    # Reject the other.
    r = client.post(f"/api/documents/{doc_b_id}/reject", headers=_h(admin_tok))
    assert r.status_code == 200 and r.json()["approval_status"] == "REJECTED", r.text
    print(f"Reject: doc {doc_b_id} -> REJECTED")

    # Sales User (no documents permission) is blocked on read and write.
    assert client.get("/api/documents", headers=_h(sales_tok)).status_code == 403
    assert client.post(f"/api/documents/{doc_a_id}/approve", headers=_h(sales_tok)).status_code == 403
    print("RBAC: Sales User 403 on list and approve")

    # Missing document -> 404.
    assert client.post("/api/documents/999999999/approve", headers=_h(admin_tok)).status_code == 404
    print("Missing document -> 404")

    # Persisted in the DB.
    session = get_session()
    try:
        a = session.get(Document, doc_a_id)
        b = session.get(Document, doc_b_id)
        assert a.approval_status == "APPROVED" and a.approved_by == admin_name and a.approved_date is not None
        assert b.approval_status == "REJECTED"
        # Cleanup fixtures + test users (soft delete / deactivate).
        a.is_deleted = True
        b.is_deleted = True
        session.commit()
        auth.deactivate_user(session, admin_id, created_by="check_milestone29c")
        auth.deactivate_user(session, sales_id, created_by="check_milestone29c")
    finally:
        session.close()

    print("PASS")


if __name__ == "__main__":
    main()
