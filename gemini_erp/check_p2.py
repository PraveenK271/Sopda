"""Patch v1.1.0 P2 check: line discount + special discount on purchases.

Asserts:
- a bill with no discount fields at all saves and totals exactly as before the
  patch (Rule B)
- 10 units @ Rs 100 with a 10% line discount -> taxable 900, GST on 900
- two lines at different GST rates with a bill-level special discount: the
  apportioned amounts sum EXACTLY to the special discount, and each line's GST
  is computed on its own post-apportionment taxable value
- discount_percent = 150 is rejected; special_discount > net value is rejected
- blank / None / "" discounts are accepted and treated as 0
- the journal balances and its Input GST equals the net GST; the Purchase
  debit is the net taxable value (no separate discount ledger)
- the Purchase Register shows net (post-discount) figures; editing a
  discounted bill keeps its discounts

ALWAYS runs on a throwaway SQLite file (GEMINI_DB_URL overridden below).

Run with: python check_p2.py
"""

import os
import tempfile

_DB_FILE = os.path.join(tempfile.mkdtemp(prefix="gemini_check_p2_"), "check_p2.db")
os.environ["GEMINI_DB_URL"] = f"sqlite:///{_DB_FILE}"

from datetime import date  # noqa: E402
from decimal import ROUND_HALF_UP, Decimal  # noqa: E402

from sqlalchemy import false  # noqa: E402

from create_db import initialize_database  # noqa: E402
from database import engine, get_session  # noqa: E402
from models import JournalEntry, LedgerAccount, PurchaseInvoiceItem  # noqa: E402
from services.accounting_service import AccountingService  # noqa: E402
from services.gst_report_service import GstReportService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.migration_service import MigrationService  # noqa: E402
from services.purchase_service import PurchaseService, calculate_purchase  # noqa: E402
from services.supplier_service import SupplierService  # noqa: E402

TODAY = date.today()
D = Decimal


def _raises(fn, *fragments) -> str:
    try:
        fn()
    except ValueError as exc:
        msg = str(exc)
        for fragment in fragments:
            assert fragment.lower() in msg.lower(), (fragment, msg)
        return msg
    raise AssertionError("expected ValueError")


def _entry_for(invoice_id):
    session = get_session()
    try:
        entry = (
            session.query(JournalEntry)
            .filter(
                JournalEntry.reference_type == "PURCHASE",
                JournalEntry.reference_id == invoice_id,
                JournalEntry.is_deleted == false(),
            )
            .one()
        )
        by_code = {}
        for line in entry.lines:
            code = session.get(LedgerAccount, line.account_id).code or "PARTY"
            by_code[code] = (D(str(line.debit)), D(str(line.credit)))
        return by_code
    finally:
        session.close()


def _tb_balances() -> bool:
    tb = AccountingService.get_trial_balance()
    return round(sum(r["debit"] for r in tb), 2) == round(sum(r["credit"] for r in tb), 2)


def main():
    assert "check_p2" in str(engine.url), f"refusing to run on {engine.url}"
    initialize_database()
    session = get_session()
    try:
        MigrationService().run_pending(session, applied_by="check_p2")
    finally:
        session.close()

    items, purch = ItemService(), PurchaseService()
    a18 = items.add_item(code="P2-A18", name="Item 18%", gst_rate=18, opening_stock=0)
    b5 = items.add_item(code="P2-B5", name="Item 5%", gst_rate=5, opening_stock=0)
    local = SupplierService().add_supplier(name="P2 Local", state="Andhra Pradesh")
    outside = SupplierService().add_supplier(name="P2 Outside", state="Karnataka")

    # [1] Rule B: no discount fields at all -> exactly the pre-patch arithmetic.
    inv = purch.create_purchase_invoice(
        "P2-NODISC", TODAY, local.id,
        [{"item_id": a18.id, "quantity": 3, "rate": "250.50"},
         {"item_id": b5.id, "quantity": 7, "rate": "19.99"}],
    )
    old_taxable = D("751.50") + D("139.93")  # qty x rate per line, as before
    # GST the pre-patch way, independently of the new code: round per line,
    # then halve for an in-state supplier.
    old_gst = D("0")
    for amount, rate in ((D("751.50"), 18), (D("139.93"), 5)):
        gst = (amount * rate / 100).quantize(D("0.01"), rounding=ROUND_HALF_UP)
        half = (gst / 2).quantize(D("0.01"), rounding=ROUND_HALF_UP)
        old_gst += half * 2
    assert D(str(inv.taxable_amount)) == old_taxable, inv.taxable_amount
    assert D(str(inv.total)) == old_taxable + old_gst, (inv.total, old_taxable + old_gst)
    assert D(str(inv.special_discount)) == 0 and D(str(inv.total_discount)) == 0
    print(f"[1] no-discount bill: taxable {inv.taxable_amount}, total {inv.total} - "
          "identical to the pre-patch formula OK")

    # [2] 10 @ 100 with 10% line discount -> taxable 900, GST on 900
    inv = purch.create_purchase_invoice(
        "P2-LINE10", TODAY, local.id,
        [{"item_id": a18.id, "quantity": 10, "rate": 100, "discount_percent": 10}],
    )
    assert D(str(inv.taxable_amount)) == D("900.00"), inv.taxable_amount
    assert D(str(inv.cgst)) == D("81.00") and D(str(inv.sgst)) == D("81.00"), (inv.cgst, inv.sgst)
    assert D(str(inv.total)) == D("1062.00") and D(str(inv.total_discount)) == D("100.00")
    je = _entry_for(inv.id)
    assert je["PURCHASE"] == (D("900.00"), D("0")), je["PURCHASE"]
    assert je["CGST_INPUT"][0] + je["SGST_INPUT"][0] == D("162.00")
    assert je["PARTY"] == (D("0"), D("1062.00"))
    print("[2] 10 x 100 less 10%: taxable 900, CGST 81 + SGST 81, total 1062; journal posts "
          "net Purchase 900 OK")

    # [3] two GST rates + special discount: exact apportionment, per-line GST
    lines = [
        {"item_id": a18.id, "quantity": 7, "rate": 143, "discount_percent": ""},        # 1001.00
        {"item_id": b5.id, "quantity": 3, "rate": "333.33", "discount_percent": "2.5"},  # 999.99 -> 974.99
    ]
    special = D("100.01")
    calc = calculate_purchase(
        [{**l, "gst_rate": g} for l, g in zip(lines, (18, 5))], special, "Andhra Pradesh"
    )
    apportioned = [p["apportioned"] for p in calc["lines"]]
    assert sum(apportioned) == special, (apportioned, special)
    for p in calc["lines"]:
        assert p["taxable"] == p["net"] - p["apportioned"]
        expected_gst = (p["taxable"] * D(str(p["gst_rate"])) / 100).quantize(
            D("0.01"), rounding=ROUND_HALF_UP)
        # split_gst halves the rounded GST; allow the 1-paisa half-split effect
        assert abs(p["gst_amount"] - expected_gst) <= D("0.01"), (p["gst_amount"], expected_gst)
    inv = purch.create_purchase_invoice("P2-SPECIAL", TODAY, local.id, lines, special_discount=special)
    assert D(str(inv.special_discount)) == special
    assert D(str(inv.taxable_amount)) == calc["totals"]["taxable"]
    assert D(str(inv.total_discount)) == calc["totals"]["line_discount"] + special
    gross = D("1001.00") + D("999.99")
    assert D(str(inv.taxable_amount)) == gross - D(str(inv.total_discount))
    session = get_session()
    try:
        saved = (
            session.query(PurchaseInvoiceItem)
            .filter(PurchaseInvoiceItem.invoice_id == inv.id)
            .order_by(PurchaseInvoiceItem.id)
            .all()
        )
        for row, p in zip(saved, calc["lines"]):
            assert D(str(row.amount)) == p["taxable"] and D(str(row.gst_amount)) == p["gst_amount"]
    finally:
        session.close()
    je = _entry_for(inv.id)
    net_gst = D(str(inv.cgst)) + D(str(inv.sgst)) + D(str(inv.igst))
    assert je["CGST_INPUT"][0] + je["SGST_INPUT"][0] == net_gst
    assert je["PURCHASE"][0] == D(str(inv.taxable_amount))
    dr = sum(v[0] for v in je.values())
    cr = sum(v[1] for v in je.values())
    assert dr == cr == D(str(inv.total)), (dr, cr, inv.total)
    print(f"[3] special {special} over 18% + 5% lines apportioned {apportioned} "
          f"(sum exact); GST per line on post-apportionment taxable; journal balances, "
          f"Input GST {net_gst} = net GST OK")

    # [3b] out-of-state supplier: IGST, still on the net value
    inv = purch.create_purchase_invoice(
        "P2-IGST", TODAY, outside.id,
        [{"item_id": a18.id, "quantity": 10, "rate": 100, "discount_percent": 10}],
        special_discount=100,
    )
    assert D(str(inv.taxable_amount)) == D("800.00") and D(str(inv.igst)) == D("144.00")
    assert _entry_for(inv.id)["IGST_INPUT"][0] == D("144.00")
    print("[3b] out-of-state: taxable 800 after both discounts, IGST 144 OK")

    # [4] guard rails
    _raises(lambda: purch.create_purchase_invoice(
        "P2-BAD1", TODAY, local.id,
        [{"item_id": a18.id, "quantity": 1, "rate": 100, "discount_percent": 150}]),
        "between 0 and 100")
    _raises(lambda: purch.create_purchase_invoice(
        "P2-BAD2", TODAY, local.id,
        [{"item_id": a18.id, "quantity": 1, "rate": 100, "discount_percent": 10}],
        special_discount=91), "cannot exceed")
    _raises(lambda: purch.create_purchase_invoice(
        "P2-BAD3", TODAY, local.id,
        [{"item_id": a18.id, "quantity": 1, "rate": 100}], special_discount=-5), "negative")
    names = {i["invoice_no"] for i in purch.list_purchase_invoices()}
    assert not names & {"P2-BAD1", "P2-BAD2", "P2-BAD3"}, "a rejected bill must not be saved"
    print("[4] discount 150% rejected; special discount > net rejected; negative rejected; "
          "nothing saved OK")

    # [5] blank / None / "" discounts are 0, never an error
    for n, (pct, spc) in enumerate(((None, None), ("", ""), ("   ", "  ")), start=1):
        inv = purch.create_purchase_invoice(
            f"P2-BLANK{n}", TODAY, local.id,
            [{"item_id": a18.id, "quantity": 2, "rate": 50, "discount_percent": pct}],
            special_discount=spc,
        )
        assert D(str(inv.taxable_amount)) == D("100.00") and D(str(inv.total_discount)) == 0
    print("[5] None / '' / whitespace discounts accepted and treated as 0 OK")

    # [6] edit keeps discounts; register shows net
    special_inv = next(i for i in purch.list_purchase_invoices() if i["invoice_no"] == "P2-SPECIAL")
    details = purch.get_purchase_invoice_details(special_inv["id"])
    assert details["special_discount"] == float(special)
    assert details["lines"][1]["discount_percent"] == 2.5
    purch.update_purchase_invoice(
        special_inv["id"], "P2-SPECIAL", TODAY, local.id,
        [{"item_id": l["item_id"], "quantity": l["quantity"], "rate": l["rate"],
          "discount_percent": l["discount_percent"]} for l in details["lines"]],
        special_discount=details["special_discount"],
    )
    after = purch.get_purchase_invoice_details(special_inv["id"])
    assert after["total"] == details["total"] and after["total_discount"] == details["total_discount"]
    register = GstReportService.get_purchase_register(TODAY, TODAY)
    reg_taxable = round(sum(r["taxable_amount"] for r in register if r["invoice_no"] == "P2-SPECIAL"), 2)
    assert reg_taxable == after["taxable_amount"], (reg_taxable, after["taxable_amount"])
    print(f"[6] edit preserves discounts (total {after['total']}); Purchase Register taxable "
          f"{reg_taxable} = net OK")

    assert _tb_balances()
    print("[7] trial balance balances OK")
    print("\nAll P2 (purchase discount) checks passed.")


if __name__ == "__main__":
    main()
