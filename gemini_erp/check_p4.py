"""Patch v1.1.0 P4 check: credit notes received from suppliers.

Asserts:
- a GST credit note of Rs 1,180 (1,000 + 9% + 9%) reduces the supplier balance
  by 1,180, credits Discount Received 1,000 and Input CGST / SGST 90 each
- a commercial credit note of Rs 1,180 reduces the supplier balance by 1,180,
  credits Discount Received 1,180 and leaves EVERY GST ledger untouched
- both journal entries balance; the Trial Balance still balances
- supplier outstanding and the supplier ledger drop by the note total
- rejected: components not summing to the total; SGST + IGST together; the
  wrong tax head for the supplier's state; note_type omitted; GOODS_RETURN
  (with the purchase-return message); a duplicate number from the SAME supplier
- accepted: the same credit_note_no from two different suppliers
- no stock movement is written; linked-invoice warning; IMS status rules;
  the 30 November cut-off; the register exports to Excel and PDF

ALWAYS runs on a throwaway SQLite file (GEMINI_DB_URL overridden below).

Run with: python check_p4.py
"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="gemini_check_p4_")
os.environ["GEMINI_DB_URL"] = f"sqlite:///{os.path.join(_TMP, 'check_p4.db')}"

from datetime import date  # noqa: E402

from sqlalchemy import func  # noqa: E402

from create_db import initialize_database  # noqa: E402
from database import engine, get_session  # noqa: E402
from models import JournalEntry, StockTransaction, Supplier  # noqa: E402
from reports.credit_note_register import export_excel, export_pdf  # noqa: E402
from services.accounting_service import AccountingService  # noqa: E402
from services.credit_note_service import (  # noqa: E402
    GOODS_RETURN_MESSAGE,
    REF_SUPPLIER_CREDIT_NOTE,
    CreditNoteService,
    declaration_deadline,
    deadline_status,
)
from services.item_service import ItemService  # noqa: E402
from services.migration_service import MigrationService  # noqa: E402
from services.purchase_service import PurchaseService  # noqa: E402
from services.supplier_service import SupplierService  # noqa: E402

TODAY = date.today()
GST_CODES = ("CGST_INPUT", "SGST_INPUT", "IGST_INPUT", "CGST_OUTPUT", "SGST_OUTPUT", "IGST_OUTPUT")
notes = CreditNoteService()


def _balance(account_id) -> float:
    """Signed closing balance: + = Dr, - = Cr."""
    ledger = AccountingService.get_ledger(account_id)
    sign = 1 if ledger["closing_balance_type"] == "Dr" else -1
    return round(sign * ledger["closing_balance"], 2)


def _code_balance(code) -> float:
    session = get_session()
    try:
        account_id = AccountingService.get_account_by_code(session, code).id
    finally:
        session.close()
    return _balance(account_id)


def _supplier_ledger_id(supplier_id) -> int:
    session = get_session()
    try:
        return session.get(Supplier, supplier_id).ledger_account.id
    finally:
        session.close()


def _outstanding(supplier_id) -> float:
    for row in AccountingService.get_outstanding_suppliers():
        if row["supplier_id"] == supplier_id:
            return row["outstanding"]
    return 0.0


def _tb_balances() -> bool:
    tb = AccountingService.get_trial_balance()
    return round(sum(r["debit"] for r in tb), 2) == round(sum(r["credit"] for r in tb), 2)


def _stock_rows() -> int:
    session = get_session()
    try:
        return session.query(func.count(StockTransaction.id)).scalar()
    finally:
        session.close()


def _raises(data, fragment):
    try:
        notes.create_credit_note(data, created_by="check_p4")
    except ValueError as exc:
        assert fragment.lower() in str(exc).lower(), (fragment, str(exc))
        return str(exc)
    raise AssertionError(f"expected rejection containing '{fragment}'")


def _note(supplier_id, no, note_type, **amounts):
    return {
        "credit_note_no": no, "credit_note_date": TODAY, "supplier_id": supplier_id,
        "note_type": note_type, "reason": "DISCOUNT", **amounts,
    }


def main():
    assert "check_p4" in str(engine.url), f"refusing to run on {engine.url}"
    initialize_database()
    session = get_session()
    try:
        MigrationService().run_pending(session, applied_by="check_p4")
        assert AccountingService.get_account_by_code(session, "DISCOUNT_RECEIVED").account_type == "INCOME"
    finally:
        session.close()

    local = SupplierService().add_supplier(name="P4 Local", state="Andhra Pradesh").id
    other_local = SupplierService().add_supplier(name="P4 Local Two", state="Andhra Pradesh").id
    outside = SupplierService().add_supplier(name="P4 Outside", state="Karnataka").id
    item = ItemService().add_item(code="P4-I", name="P4 Item", gst_rate=18).id
    purchase = PurchaseService().create_purchase_invoice(
        "P4-BILL", TODAY, local, [{"item_id": item, "quantity": 50, "rate": 100}])  # 5,900 owed
    ledger_id = _supplier_ledger_id(local)
    stock_rows_before = _stock_rows()

    # [1] GST credit note 1,180
    before = {"supplier": _balance(ledger_id), "outstanding": _outstanding(local),
              "disc": _code_balance("DISCOUNT_RECEIVED"),
              "cgst": _code_balance("CGST_INPUT"), "sgst": _code_balance("SGST_INPUT")}
    gst_note = notes.create_credit_note(
        _note(local, "CN-1", "GST", taxable_value=1000, cgst=90, sgst=90, total_amount=1180,
              linked_purchase_invoice_id=purchase.id),
        created_by="check_p4",
    )
    assert gst_note.warnings == []
    assert round(_balance(ledger_id) - before["supplier"], 2) == 1180.0  # Cr balance shrinks by 1180
    assert round(before["outstanding"] - _outstanding(local), 2) == 1180.0
    assert round(_code_balance("DISCOUNT_RECEIVED") - before["disc"], 2) == -1000.0
    assert round(_code_balance("CGST_INPUT") - before["cgst"], 2) == -90.0
    assert round(_code_balance("SGST_INPUT") - before["sgst"], 2) == -90.0
    print("[1] GST note 1,180: supplier -1,180 (outstanding "
          f"{before['outstanding']:.2f} -> {_outstanding(local):.2f}), Discount Received Cr 1,000, "
          "Input CGST Cr 90, Input SGST Cr 90 OK")

    # [2] commercial credit note 1,180: no GST ledger moves
    gst_before = {code: _code_balance(code) for code in GST_CODES}
    sup_before, disc_before, out_before = _balance(ledger_id), _code_balance("DISCOUNT_RECEIVED"), _outstanding(local)
    notes.create_credit_note(_note(local, "CN-2", "COMMERCIAL", total_amount=1180), created_by="check_p4")
    assert round(_balance(ledger_id) - sup_before, 2) == 1180.0
    assert round(out_before - _outstanding(local), 2) == 1180.0
    assert round(_code_balance("DISCOUNT_RECEIVED") - disc_before, 2) == -1180.0
    assert {code: _code_balance(code) for code in GST_CODES} == gst_before, "no GST ledger may move"
    print("[2] commercial note 1,180: supplier -1,180, Discount Received Cr 1,180, every GST "
          "ledger untouched OK")

    # [3] journals balance; TB balances; supplier ledger shows the notes
    session = get_session()
    try:
        entries = session.query(JournalEntry).filter(JournalEntry.reference_type == REF_SUPPLIER_CREDIT_NOTE).all()
        assert len(entries) == 2
        for entry in entries:
            assert sum(float(l.debit) for l in entry.lines) == sum(float(l.credit) for l in entry.lines)
    finally:
        session.close()
    assert _tb_balances()
    ledger = AccountingService.get_ledger(ledger_id)
    assert sum(1 for e in ledger["entries"] if e["reference_type"] == REF_SUPPLIER_CREDIT_NOTE) == 2
    assert _stock_rows() == stock_rows_before, "credit notes must not touch stock"
    print("[3] both journals balance, trial balance balances, supplier ledger lists both notes, "
          "no stock rows written OK")

    # [4] rejections
    _raises(_note(local, "BAD-1", "GST", taxable_value=1000, cgst=90, sgst=90, total_amount=1200), "does not match")
    _raises(_note(local, "BAD-2", "GST", taxable_value=1000, sgst=90, igst=90, total_amount=1180), "never both")
    _raises(_note(local, "BAD-3", "GST", taxable_value=1000, igst=180, total_amount=1180), "CGST + SGST")
    _raises(_note(outside, "BAD-4", "GST", taxable_value=1000, cgst=90, sgst=90, total_amount=1180), "IGST")
    _raises(_note(local, "BAD-5", None, total_amount=100), "credit note type")
    _raises(_note(local, "BAD-6", "", total_amount=100), "credit note type")
    msg = _raises({**_note(local, "BAD-7", "COMMERCIAL", total_amount=100), "reason": "GOODS_RETURN"},
                  "Purchase Return")
    assert msg == GOODS_RETURN_MESSAGE
    _raises(_note(local, "BAD-8", "COMMERCIAL", cgst=9, total_amount=100), "no GST")
    _raises(_note(local, "CN-1", "COMMERCIAL", total_amount=100), "already recorded")
    _raises(_note(local, "BAD-9", "COMMERCIAL", total_amount=0), "greater than zero")
    _raises(_note(other_local, "BAD-10", "COMMERCIAL", total_amount=10,
                  linked_purchase_invoice_id=purchase.id), "different supplier")
    assert len(notes.list_credit_notes()) == 2, "no rejected note may be saved"
    print("[4] rejected: sum mismatch, SGST+IGST, wrong head for state (both ways), missing "
          "type, GOODS_RETURN (purchase-return message), GST on commercial, duplicate from "
          "the same supplier, zero total, invoice of another supplier OK")

    # [5] accepted edge cases
    notes.create_credit_note(_note(other_local, "CN-1", "COMMERCIAL", total_amount=50), created_by="check_p4")
    igst_note = notes.create_credit_note(
        _note(outside, "CN-IG", "GST", taxable_value=500, igst=90, total_amount=590), created_by="check_p4")
    assert float(igst_note.igst) == 90.0
    rounded = notes.create_credit_note(
        _note(local, "CN-RND", "GST", taxable_value=1000, cgst=90, sgst=90, total_amount="1180.40"),
        created_by="check_p4")  # printed round-off within Rs 1
    assert float(rounded.total_amount) == 1180.40
    warned = notes.create_credit_note(
        _note(local, "CN-BIG", "COMMERCIAL", total_amount=6000, linked_purchase_invoice_id=purchase.id),
        created_by="check_p4")
    assert any("more than the linked purchase invoice" in w for w in warned.warnings), warned.warnings
    assert _tb_balances()
    print("[5] accepted: same number from a different supplier, IGST note from an out-of-state "
          "supplier, Rs 0.40 round-off (still balances), over-invoice note with a warning OK")

    # [6] IMS status
    try:
        commercial_id = next(n["id"] for n in notes.list_credit_notes() if n["credit_note_no"] == "CN-2")
        notes.update_ims_status(commercial_id, "ACCEPTED", True, 10)
        raise AssertionError("commercial note cannot reverse ITC")
    except ValueError:
        pass
    notes.update_ims_status(gst_note.id, "ACCEPTED", True, "")
    row = next(n for n in notes.list_credit_notes() if n["id"] == gst_note.id)
    assert row["ims_status"] == "ACCEPTED" and row["itc_reversed"] and row["itc_reversal_amount"] == 180.0
    pending = notes.list_credit_notes(pending_only=True)
    assert gst_note.id not in {n["id"] for n in pending} and len(pending) == 5
    assert len(notes.list_credit_notes(supplier_id=outside)) == 1
    print("[6] IMS: commercial ITC reversal refused; GST note accepted with full ITC 180; "
          "pending / supplier filters OK")

    # [7] 30 November cut-off
    assert declaration_deadline(date(2026, 5, 10)) == date(2027, 11, 30)
    assert declaration_deadline(date(2026, 2, 1)) == date(2026, 11, 30)
    assert deadline_status("GST", date(2025, 6, 1), today=date(2026, 12, 1)) == "PASSED"
    assert deadline_status("GST", date(2025, 6, 1), today=date(2026, 10, 15)) == "APPROACHING"
    assert deadline_status("GST", date(2026, 6, 1), today=date(2026, 10, 15)) == "OK"
    assert deadline_status("COMMERCIAL", date(2025, 6, 1)) is None
    print("[7] declaration cut-off: FY Apr-Mar -> 30 Nov after FY end; PASSED / APPROACHING / "
          "OK flags OK")

    # [8] register exports
    rows = notes.list_credit_notes()
    xlsx = export_excel(rows, os.path.join(_TMP, "register.xlsx"), "Register")
    pdf = export_pdf(rows, os.path.join(_TMP, "register.pdf"), "Register")
    assert os.path.getsize(xlsx) > 0 and os.path.getsize(pdf) > 0
    print(f"[8] register exported: {len(rows)} rows to Excel and PDF OK")

    print("\nAll P4 (supplier credit note) checks passed.")


if __name__ == "__main__":
    main()
