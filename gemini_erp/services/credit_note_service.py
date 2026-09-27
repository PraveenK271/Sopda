"""Credit notes RECEIVED from suppliers as discounts (patch v1.1.0, P4).

Two documents that must not be blurred — the type decides the books:

- GST credit note (Section 34, CGST Act): reduces the taxable value AND the
  tax of the original supply, so the input tax credit on it is reversed:
      Dr Supplier            total
         Cr Discount Received    taxable value
         Cr Input CGST/SGST/IGST the GST on the note
- Commercial / financial credit note (Circular 251/08/2025-GST): carries no
  GST and needs no ITC reversal, so no GST ledger is touched at all:
      Dr Supplier            total
         Cr Discount Received    total

Recording one as the other misstates ITC, so ``note_type`` is mandatory with
no default. Discounts only — this never touches stock: goods physically sent
back belong in Purchase Return, and a GOODS_RETURN reason is refused.

``ims_status`` / ``itc_reversed`` are maintained by hand against the GST
portal's IMS dashboard; nothing here talks to the portal. Not tax advice —
the accountant confirms the filing treatment.
"""

import logging
from datetime import date as date_type
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import false
from sqlalchemy.exc import IntegrityError

from database import get_session
from models import PurchaseInvoice, Supplier, SupplierCreditNote
from services.accounting_service import AccountingService
from services.chart_of_accounts import (
    CGST_INPUT,
    DISCOUNT_RECEIVED,
    IGST_INPUT,
    SGST_INPUT,
)
from services.gst_service import OUR_STATE
from services.period_lock_service import PeriodLockService

logger = logging.getLogger(__name__)

NOTE_TYPE_GST = "GST"
NOTE_TYPE_COMMERCIAL = "COMMERCIAL"
NOTE_TYPES = (NOTE_TYPE_GST, NOTE_TYPE_COMMERCIAL)

REASON_GOODS_RETURN = "GOODS_RETURN"
REASONS = ("DISCOUNT", "RATE_DIFFERENCE", "QUALITY_CLAIM", "SCHEME", REASON_GOODS_RETURN)

IMS_STATUSES = ("PENDING", "ACCEPTED", "REJECTED")

REF_SUPPLIER_CREDIT_NOTE = "SUPPLIER_CREDIT_NOTE"

GOODS_RETURN_MESSAGE = (
    "Use Purchase Return for goods physically sent back — this screen does not adjust stock."
)

# A GST note's parts may differ from its printed total by round-off, up to Rs 1.
SUM_TOLERANCE = Decimal("1.00")
# How close to the 30 November cut-off a pending GST note gets flagged.
DEADLINE_WARNING_DAYS = 60

_PAISA = Decimal("0.01")


def _money(value, field_name: str) -> Decimal:
    """Rupee amount as Decimal; blank / None means 0."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal("0.00")
    try:
        return Decimal(str(value).strip()).quantize(_PAISA, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"{field_name} must be a number, got '{value}'")


def declaration_deadline(note_date: date_type) -> date_type:
    """30 November after the end of the note's financial year (Apr-Mar).

    Section 34 also ends the window at the annual return filing if that is
    earlier — the software cannot know that date, so the register flags against
    30 November and the accountant watches the other.
    """
    fy_end_year = note_date.year + 1 if note_date.month >= 4 else note_date.year
    return date_type(fy_end_year, 11, 30)


def deadline_status(note_type: str, note_date: date_type, today: date_type | None = None) -> str | None:
    """'PASSED' / 'APPROACHING' / 'OK' for a GST note; None for a commercial one."""
    if note_type != NOTE_TYPE_GST:
        return None
    today = today or date_type.today()
    deadline = declaration_deadline(note_date)
    if today > deadline:
        return "PASSED"
    if (deadline - today).days <= DEADLINE_WARNING_DAYS:
        return "APPROACHING"
    return "OK"


class CreditNoteService:
    """Record, list and reconcile supplier credit notes."""

    # ----- create --------------------------------------------------------

    def validate(self, data: dict) -> list[str]:
        """Run every check without writing. Raises ValueError for anything
        that blocks the save; returns warnings for the user to confirm."""
        session = get_session()
        try:
            _clean, warnings = self._validate(session, data)
            return warnings
        finally:
            session.close()

    def create_credit_note(self, data: dict, created_by: str | None = None) -> SupplierCreditNote:
        """Record a supplier credit note and post its journal — one transaction.

        data: credit_note_no, credit_note_date, supplier_id, note_type, reason,
        total_amount, and for a GST note taxable_value/cgst/sgst/igst; optional
        linked_purchase_invoice_id and notes. The returned note carries the
        non-blocking ``warnings`` as a transient attribute.
        """
        session = get_session()
        try:
            clean, warnings = self._validate(session, data)
            note = SupplierCreditNote(**clean, created_by=created_by)
            session.add(note)
            session.flush()  # note.id for the journal reference

            supplier = session.get(Supplier, clean["supplier_id"])
            self._post_journal(session, note, supplier, created_by)

            session.commit()
            session.refresh(note)
            note.warnings = warnings
            logger.info(
                "Recorded %s credit note %s from supplier %s for %s",
                note.note_type, note.credit_note_no, supplier.name, note.total_amount,
            )
            return note
        except IntegrityError:
            session.rollback()
            raise ValueError(
                f"Credit note '{data.get('credit_note_no')}' is already recorded for this supplier."
            )
        except Exception:
            session.rollback()
            logger.exception("Failed to record supplier credit note %s", data.get("credit_note_no"))
            raise
        finally:
            session.close()

    def _validate(self, session, data: dict) -> tuple[dict, list[str]]:
        warnings: list[str] = []

        # First, whatever else is filled in: goods sent back are not this screen.
        reason = (data.get("reason") or "").strip().upper()
        if reason == REASON_GOODS_RETURN:
            raise ValueError(GOODS_RETURN_MESSAGE)

        note_type = (data.get("note_type") or "").strip().upper()
        if note_type not in NOTE_TYPES:
            raise ValueError(
                "Choose the credit note type: 'GST' (carries GST — input tax credit is "
                "reversed) or 'COMMERCIAL' (no GST — nothing to reverse)."
            )

        if reason not in REASONS:
            raise ValueError(f"Reason must be one of: {', '.join(r for r in REASONS if r != REASON_GOODS_RETURN)}.")

        credit_note_no = (data.get("credit_note_no") or "").strip()
        if not credit_note_no:
            raise ValueError("The supplier's credit note number is required.")

        note_date = data.get("credit_note_date")
        if not isinstance(note_date, date_type):
            raise ValueError("The credit note date is required.")
        PeriodLockService().check_not_locked(note_date)

        supplier = session.get(Supplier, data.get("supplier_id"))
        if supplier is None or supplier.is_deleted:
            raise ValueError("Select the supplier who issued the credit note.")

        duplicate = (
            session.query(SupplierCreditNote.id)
            .filter(
                SupplierCreditNote.supplier_id == supplier.id,
                SupplierCreditNote.credit_note_no == credit_note_no,
                SupplierCreditNote.is_deleted == false(),
            )
            .first()
        )
        if duplicate is not None:
            raise ValueError(
                f"Credit note '{credit_note_no}' from {supplier.name} is already recorded."
            )

        total = _money(data.get("total_amount"), "Total amount")
        if total <= 0:
            raise ValueError("The credit note total must be greater than zero.")
        taxable = _money(data.get("taxable_value"), "Taxable value")
        cgst = _money(data.get("cgst"), "CGST")
        sgst = _money(data.get("sgst"), "SGST")
        igst = _money(data.get("igst"), "IGST")
        if min(taxable, cgst, sgst, igst) < 0:
            raise ValueError("Credit note amounts cannot be negative.")

        if note_type == NOTE_TYPE_GST:
            if taxable <= 0:
                raise ValueError("A GST credit note needs its taxable value.")
            if abs(taxable + cgst + sgst + igst - total) > SUM_TOLERANCE:
                raise ValueError(
                    f"Taxable {taxable} + CGST {cgst} + SGST {sgst} + IGST {igst} = "
                    f"{taxable + cgst + sgst + igst}, which does not match the total {total}."
                )
            if igst and (cgst or sgst):
                raise ValueError("A credit note carries either CGST + SGST or IGST, never both.")
            in_state = supplier.state == OUR_STATE
            if in_state and igst:
                raise ValueError(
                    f"{supplier.name} is in {OUR_STATE}: the note should carry CGST + SGST, not IGST."
                )
            if not in_state and (cgst or sgst):
                raise ValueError(
                    f"{supplier.name} is outside {OUR_STATE}: the note should carry IGST, "
                    "not CGST + SGST."
                )
            if deadline_status(note_type, note_date) == "PASSED":
                warnings.append(
                    f"This GST credit note is past the {declaration_deadline(note_date):%d-%m-%Y} "
                    "declaration cut-off for its financial year. Check with the accountant "
                    "before claiming the reduction."
                )
        else:
            if cgst or sgst or igst:
                raise ValueError(
                    "A commercial credit note carries no GST — leave CGST, SGST and IGST empty."
                )
            taxable = Decimal("0.00")  # the taxable value only means something on a GST note

        linked_id = data.get("linked_purchase_invoice_id") or None
        if linked_id is not None:
            invoice = session.get(PurchaseInvoice, linked_id)
            if invoice is None or invoice.is_deleted:
                raise ValueError(f"Purchase invoice {linked_id} not found.")
            if invoice.supplier_id != supplier.id:
                raise ValueError("The linked purchase invoice belongs to a different supplier.")
            if total > Decimal(str(invoice.total)):
                warnings.append(
                    f"The credit note total {total} is more than the linked purchase invoice "
                    f"{invoice.invoice_no}'s total {Decimal(str(invoice.total)):.2f}."
                )

        clean = {
            "credit_note_no": credit_note_no,
            "credit_note_date": note_date,
            "supplier_id": supplier.id,
            "linked_purchase_invoice_id": linked_id,
            "note_type": note_type,
            "reason": reason,
            "taxable_value": taxable,
            "cgst": cgst,
            "sgst": sgst,
            "igst": igst,
            "total_amount": total,
            "itc_reversed": False,
            "itc_reversal_amount": Decimal("0.00"),
            "ims_status": "PENDING",
            "notes": (data.get("notes") or "").strip()[:500] or None,
        }
        return clean, warnings

    @staticmethod
    def _post_journal(session, note, supplier, created_by) -> None:
        supp_ledger = supplier.ledger_account
        if supp_ledger is None:
            raise ValueError(f"Supplier {supplier.id} has no linked ledger account.")
        total = Decimal(str(note.total_amount))
        discount_acct = AccountingService.get_account_by_code(session, DISCOUNT_RECEIVED)
        lines = [{"account_id": supp_ledger.id, "debit": total, "credit": Decimal("0")}]

        if note.note_type == NOTE_TYPE_GST:
            gst_parts = (
                (CGST_INPUT, Decimal(str(note.cgst))),
                (SGST_INPUT, Decimal(str(note.sgst))),
                (IGST_INPUT, Decimal(str(note.igst))),
            )
            gst_total = sum((amount for _code, amount in gst_parts), Decimal("0"))
            # Discount Received takes total - GST (= the taxable value, plus any
            # printed round-off within the Rs 1 tolerance), so the entry always
            # balances without inventing a round-off ledger.
            lines.append({"account_id": discount_acct.id, "debit": Decimal("0"), "credit": total - gst_total})
            for code, amount in gst_parts:
                if amount:
                    acct = AccountingService.get_account_by_code(session, code)
                    lines.append({"account_id": acct.id, "debit": Decimal("0"), "credit": amount})
        else:
            lines.append({"account_id": discount_acct.id, "debit": Decimal("0"), "credit": total})

        AccountingService.post_journal_entry(
            session,
            date=note.credit_note_date,
            reference_type=REF_SUPPLIER_CREDIT_NOTE,
            reference_id=note.id,
            lines=lines,
            narration=f"{note.note_type.title()} credit note {note.credit_note_no} from {supplier.name}",
            created_by=created_by,
        )

    # ----- read ------------------------------------------------------------

    def list_credit_notes(
        self,
        supplier_id: int | None = None,
        from_date: date_type | None = None,
        to_date: date_type | None = None,
        pending_only: bool = False,
        deadline_only: bool = False,
    ) -> list[dict]:
        """Credit notes, oldest first, for the list view and the register.

        pending_only: IMS status still PENDING. deadline_only: GST notes still
        PENDING whose 30 November cut-off is near or past.
        """
        session = get_session()
        try:
            query = session.query(SupplierCreditNote).filter(SupplierCreditNote.is_deleted == false())
            if supplier_id:
                query = query.filter(SupplierCreditNote.supplier_id == supplier_id)
            if from_date:
                query = query.filter(SupplierCreditNote.credit_note_date >= from_date)
            if to_date:
                query = query.filter(SupplierCreditNote.credit_note_date <= to_date)
            if pending_only or deadline_only:
                query = query.filter(SupplierCreditNote.ims_status == "PENDING")
            notes = query.order_by(SupplierCreditNote.credit_note_date, SupplierCreditNote.id).all()

            result = []
            for n in notes:
                status = deadline_status(n.note_type, n.credit_note_date)
                attention = n.ims_status == "PENDING" and status in ("APPROACHING", "PASSED")
                if deadline_only and not attention:
                    continue
                gst = float(n.cgst) + float(n.sgst) + float(n.igst)
                result.append({
                    "id": n.id,
                    "credit_note_no": n.credit_note_no,
                    "credit_note_date": n.credit_note_date,
                    "supplier_id": n.supplier_id,
                    "supplier_name": n.supplier.name,
                    "supplier_gstin": n.supplier.gstin,
                    "linked_invoice_no": (
                        n.linked_purchase_invoice.invoice_no if n.linked_purchase_invoice else None
                    ),
                    "note_type": n.note_type,
                    "reason": n.reason,
                    "taxable_value": float(n.taxable_value),
                    "cgst": float(n.cgst),
                    "sgst": float(n.sgst),
                    "igst": float(n.igst),
                    "gst_total": round(gst, 2),
                    "total_amount": float(n.total_amount),
                    "itc_reversed": bool(n.itc_reversed),
                    "itc_reversal_amount": float(n.itc_reversal_amount),
                    "ims_status": n.ims_status,
                    "notes": n.notes,
                    "declaration_deadline": (
                        declaration_deadline(n.credit_note_date) if n.note_type == NOTE_TYPE_GST else None
                    ),
                    "deadline_status": status,
                    "needs_attention": attention,
                })
            return result
        except Exception:
            logger.exception("Failed to list supplier credit notes")
            raise
        finally:
            session.close()

    # ----- IMS reconciliation ---------------------------------------------

    def update_ims_status(
        self,
        credit_note_id: int,
        status: str,
        itc_reversed: bool,
        itc_reversal_amount,
        modified_by: str | None = None,
    ) -> None:
        """Record what was done on the GST portal's IMS dashboard.

        Bookkeeping only: the Input GST was already credited when the GST note
        was recorded, so this posts nothing. A commercial note has no ITC to
        reverse.
        """
        status = (status or "").strip().upper()
        if status not in IMS_STATUSES:
            raise ValueError(f"IMS status must be one of: {', '.join(IMS_STATUSES)}.")
        amount = _money(itc_reversal_amount, "ITC reversal amount")

        session = get_session()
        try:
            note = session.get(SupplierCreditNote, credit_note_id)
            if note is None or note.is_deleted:
                raise ValueError(f"Credit note {credit_note_id} not found.")
            if note.note_type == NOTE_TYPE_COMMERCIAL:
                if itc_reversed or amount:
                    raise ValueError(
                        "A commercial credit note carries no GST, so there is no ITC to reverse."
                    )
            else:
                note_gst = Decimal(str(note.cgst)) + Decimal(str(note.sgst)) + Decimal(str(note.igst))
                if itc_reversed and not amount:
                    amount = note_gst  # reversed in full unless told otherwise
                if not itc_reversed and amount:
                    raise ValueError("Tick 'ITC reversed' to record an ITC reversal amount.")
                if amount < 0 or amount > note_gst:
                    raise ValueError(
                        f"The ITC reversal amount must be between 0 and the note's GST ({note_gst})."
                    )

            note.ims_status = status
            note.itc_reversed = bool(itc_reversed)
            note.itc_reversal_amount = amount
            note.modified_by = modified_by
            session.commit()
            logger.info(
                "Credit note %s IMS status -> %s (ITC reversed=%s, %s)",
                note.credit_note_no, status, itc_reversed, amount,
            )
        except Exception:
            session.rollback()
            logger.exception("Failed to update IMS status of credit note %s", credit_note_id)
            raise
        finally:
            session.close()
