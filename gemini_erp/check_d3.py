"""Patch v1.2.0 D3 check: cancellation is visible everywhere it should be.

Two invoices, one cancelled:
- Sales Register totals = the active one only; the cancelled one is listed in
  its own section (get_cancelled_sales_register)
- GST register lines and the HSN summary exclude it
- GSTR-1 B2B / B2C exclude it and list it under "cancelled"; GSTR-3B outward
  taxable supplies exclude it (the input-tax side is untouched)
- the Sales Log still shows it, flagged CANCELLED; include_cancelled=False hides it
- the API dashboard's "sales today" excludes it
- the Cancelled Invoices report shows exactly one row, with the reason; it
  exports to Excel and PDF
- the Sequence Check reports NO gaps after a cancellation, and does report a
  real gap
- financial reports self-correct: Trial Balance balances, P&L sales = active only

ALWAYS runs on a throwaway SQLite file (GEMINI_DB_URL overridden below).

Run with: python check_d3.py
"""

import os
import tempfile

import secrets  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="gemini_check_d3_")
os.environ["GEMINI_DB_URL"] = f"sqlite:///{os.path.join(_TMP, 'check_d3.db')}"
# The API module refuses to load without a secret; this process only calls the
# dashboard function directly, so a throwaway one is enough.
os.environ["GEMINI_JWT_SECRET"] = secrets.token_hex(32)

from datetime import date  # noqa: E402

from sqlalchemy.orm import joinedload  # noqa: E402

from api.routers.dashboard import dashboard  # noqa: E402
from create_db import initialize_database  # noqa: E402
from database import engine, get_session  # noqa: E402
from models import User  # noqa: E402
from reports.cancelled_invoices import export_excel, export_pdf  # noqa: E402
from services.accounting_service import AccountingService  # noqa: E402
from services.customer_service import CustomerService  # noqa: E402
from services.gst_report_service import GstReportService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.migration_service import MigrationService  # noqa: E402
from services.sales_service import SalesService  # noqa: E402

TODAY = date.today()
FY_START = date(TODAY.year if TODAY.month >= 4 else TODAY.year - 1, 4, 1)
sales = SalesService()


def main():
    assert "check_d3" in str(engine.url), f"refusing to run on {engine.url}"
    initialize_database()
    session = get_session()
    try:
        MigrationService().run_pending(session, applied_by="check_d3")
        admin = session.query(User).options(joinedload(User.role)).filter(User.username == "admin").one()
        session.expunge(admin)
    finally:
        session.close()

    item = ItemService().add_item(code="D3-I", name="D3 Item", hsn_code="1234", gst_rate=18, opening_stock=100).id
    b2b = CustomerService().add_customer(name="D3 Registered", gstin="37ABCDE1234F1Z5", state="Andhra Pradesh").id
    b2c = CustomerService().add_customer(name="D3 Walk-in", state="Andhra Pradesh").id
    kept = sales.create_invoice("D3-001", TODAY, b2b, [{"item_id": item, "quantity": 10, "rate": 100}],
                                created_by="admin").id  # 1,000 + 180
    void = sales.create_invoice("D3-002", TODAY, b2b, [{"item_id": item, "quantity": 5, "rate": 100}],
                                created_by="admin").id   # 500 + 90
    walk_in_void = sales.create_invoice("D3-003", TODAY, b2c, [{"item_id": item, "quantity": 2, "rate": 100}],
                                        created_by="admin").id
    sales.cancel_invoice(void, "goods never dispatched", "admin")
    sales.cancel_invoice(walk_in_void, "duplicate bill", "admin")

    # [1] Sales Register
    register = GstReportService.get_sales_register(TODAY, TODAY)
    assert {r["invoice_no"] for r in register} == {"D3-001"}
    assert round(sum(r["taxable_amount"] for r in register), 2) == 1000.0
    assert round(sum(r["total"] for r in register), 2) == 1180.0
    cancelled_section = GstReportService.get_cancelled_sales_register(TODAY, TODAY)
    assert [r["invoice_no"] for r in cancelled_section] == ["D3-002", "D3-003"]
    print("[1] Sales Register: totals 1,000 / 1,180 = D3-001 only; D3-002 and D3-003 in the "
          "cancelled section OK")

    # [2] HSN summary
    hsn = GstReportService.get_hsn_summary(TODAY, TODAY, "SALES")
    assert len(hsn) == 1 and hsn[0]["quantity"] == 10.0 and hsn[0]["taxable_amount"] == 1000.0
    print("[2] HSN summary: qty 10, taxable 1,000 (cancelled lines excluded) OK")

    # [3] GSTR-1 and GSTR-3B
    g1 = GstReportService.get_gstr1_summary(TODAY, TODAY)
    assert [r["invoice_no"] for r in g1["b2b"]] == ["D3-001"]
    assert g1["b2c_small"]["taxable_value"] == 0.0, g1["b2c_small"]
    assert [r["invoice_no"] for r in g1["cancelled"]] == ["D3-002", "D3-003"]
    g3 = GstReportService.get_gstr3b_summary(TODAY, TODAY)
    out = g3["outward_taxable_supplies"]
    assert out["taxable_amount"] == 1000.0 and out["cgst"] == 90.0 and out["sgst"] == 90.0, out
    print("[3] GSTR-1: B2B D3-001 only, B2C 0, both cancelled listed separately; GSTR-3B "
          "3.1(a) taxable 1,000, CGST 90, SGST 90 OK")

    # [4] Sales Log and dashboard
    listed = {inv["invoice_no"]: inv["status"] for inv in sales.list_invoices()}
    assert listed == {"D3-001": "ACTIVE", "D3-002": "CANCELLED", "D3-003": "CANCELLED"}, listed
    assert [inv["invoice_no"] for inv in sales.list_invoices(include_cancelled=False)] == ["D3-001"]
    sales_today = dashboard(admin)["sales_today"]
    assert sales_today == {"count": 1, "total": 1180.0}, sales_today
    print("[4] Sales Log lists all three, two flagged CANCELLED; hide-cancelled leaves D3-001; "
          "dashboard sales today = 1 invoice / 1,180 OK")

    # [5] Cancelled Invoices report
    rows = sales.list_cancelled_invoices(TODAY, TODAY)
    assert [(r["invoice_no"], r["cancellation_reason"], r["cancelled_by"]) for r in rows] == [
        ("D3-002", "goods never dispatched", "admin"), ("D3-003", "duplicate bill", "admin"),
    ]
    assert rows[0]["total"] == 590.0 and rows[0]["cancelled_date"] is not None
    assert sales.list_cancelled_invoices(date(2000, 1, 1), date(2000, 12, 31)) == []
    xlsx = export_excel(rows, os.path.join(_TMP, "cancelled.xlsx"), "Cancelled Invoices")
    pdf = export_pdf(rows, os.path.join(_TMP, "cancelled.pdf"), "Cancelled Invoices")
    assert os.path.getsize(xlsx) > 0 and os.path.getsize(pdf) > 0
    print("[5] Cancelled Invoices report: one row per cancelled invoice with reason, who and "
          "amount; Excel + PDF exported OK")

    # [6] Sequence check
    seq = sales.check_invoice_sequence(FY_START, TODAY)
    assert seq["gaps"] == [], seq
    assert seq["series"][0]["first"] == "D3-001" and seq["series"][0]["last"] == "D3-003"
    sales.create_invoice("D3-005", TODAY, b2b, [{"item_id": item, "quantity": 1, "rate": 100}], created_by="admin")
    seq = sales.check_invoice_sequence(FY_START, TODAY)
    assert seq["gaps"] == [{"series": "D3-###", "missing": ["D3-004"], "count": 1}], seq
    print("[6] Sequence check: no gaps after cancelling D3-002/D3-003 (they stay in the "
          "series); a real gap (D3-004) is reported OK")

    # [7] financial reports self-correct
    tb = AccountingService.get_trial_balance()
    assert round(sum(r["debit"] for r in tb), 2) == round(sum(r["credit"] for r in tb), 2)
    pnl = AccountingService.get_profit_and_loss(FY_START, TODAY)
    income = {r["account_name"]: r["amount"] for r in pnl["income"]}
    assert income.get("Sales Account") == 1100.0, income  # 1,000 + the 100 of D3-005
    print("[7] Trial Balance balances; P&L Sales Account = 1,100 (active invoices only) with "
          "no report change — self-corrected by the reversing journals OK")

    print("\nAll D3 (cancellation visibility) checks passed.")


if __name__ == "__main__":
    main()
