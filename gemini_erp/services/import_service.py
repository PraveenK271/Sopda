"""Historical import engine (track H).

A generic read -> validate -> report -> import tool for bringing this financial
year's real trading history in from Excel. Two-stage by contract: validation
reads the whole file and writes NOTHING; the user sees every problem before
deciding to import. Per-type import methods (H2-H5) reuse the existing services
(SalesService, PurchaseService, ...) — there is no parallel save path.

All business rules live here, not in the UI (CLAUDE.md).
"""

import logging
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from sqlalchemy import false
from database import get_session
from models import Customer, ImportLog, Item, SalesInvoice, Supplier
from services.opening_balance_service import OpeningBalanceService

logger = logging.getLogger(__name__)

# The historical cut-off: transactions on/after this date are entered
# individually; everything before is collapsed into opening balances (H2).
CUTOFF_DATE = date_type(2026, 4, 1)
DATE_FORMAT = "%d-%m-%Y"

# Marker written into an extra NOTE column of the template's example row so the
# reader can skip it even if the user forgets to delete it.
EXAMPLE_MARKER = "EXAMPLE - DELETE ME"


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    kind: str = "text"          # text | date | number
    required: bool = True
    role: str | None = None      # date | item_code | quantity | rate | total |
                                 # amount | opening_qty | party_name | unique_ref |
                                 # party_type | balance_type | mode | bank_account
    description: str = ""
    example: str = ""


@dataclass(frozen=True)
class ImportTypeDef:
    key: str
    party_kind: str | None       # 'CUSTOMER' | 'SUPPLIER' | None
    columns: list[ColumnSpec]

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


# --- Column definitions per import type -------------------------------------

IMPORT_DEFS: dict[str, ImportTypeDef] = {
    "SALES": ImportTypeDef("SALES", "CUSTOMER", [
        ColumnSpec("invoice_no", "text", True, "unique_ref", "Bill-book invoice number; must be unique.", "DA001/2026-2027"),
        ColumnSpec("invoice_date", "date", True, "date", "DD-MM-YYYY, on/after 01-04-2026.", "05-04-2026"),
        ColumnSpec("customer_name", "text", True, "party_name", "Auto-created after confirmation if unknown.", "Ramesh Traders"),
        ColumnSpec("customer_gstin", "text", False, None, "Blank for B2C.", "37ABCDE1234F1Z5"),
        ColumnSpec("customer_state", "text", False, None, "Blank defaults to Andhra Pradesh.", "Andhra Pradesh"),
        ColumnSpec("item_code", "text", True, "item_code", "Must already exist in the Item Master.", "ITM-001"),
        ColumnSpec("quantity", "number", True, "quantity", "Greater than 0.", "10"),
        ColumnSpec("rate", "number", True, "rate", "Per-unit rate, excluding GST.", "100"),
        ColumnSpec("invoice_total", "number", True, "total", "Bill-book total (cross-check); repeat on every row of the invoice.", "1180"),
    ]),
    "PURCHASES": ImportTypeDef("PURCHASES", "SUPPLIER", [
        ColumnSpec("bill_no", "text", True, "unique_ref", "Supplier's bill number; unique per supplier.", "S-100"),
        ColumnSpec("bill_date", "date", True, "date", "DD-MM-YYYY, on/after 01-04-2026.", "05-04-2026"),
        ColumnSpec("supplier_name", "text", True, "party_name", "Auto-created after confirmation if unknown.", "Sri Metals"),
        ColumnSpec("supplier_gstin", "text", False, None, "Blank if unregistered.", "29ABCDE1234F1Z5"),
        ColumnSpec("supplier_state", "text", False, None, "Blank defaults to Andhra Pradesh.", "Karnataka"),
        ColumnSpec("item_code", "text", True, "item_code", "Must already exist in the Item Master.", "ITM-001"),
        ColumnSpec("quantity", "number", True, "quantity", "Greater than 0.", "50"),
        ColumnSpec("rate", "number", True, "rate", "Per-unit rate, excluding GST.", "80"),
        ColumnSpec("bill_total", "number", True, "total", "Bill total (cross-check); repeat on every row of the bill.", "4720"),
    ]),
    "OPENING_STOCK": ImportTypeDef("OPENING_STOCK", None, [
        ColumnSpec("item_code", "text", True, "item_code", "Must already exist in the Item Master.", "ITM-001"),
        ColumnSpec("opening_qty", "number", True, "opening_qty", "Stock quantity ON 31-03-2026 (NOT today's count).", "60"),
    ]),
    "OPENING_BALANCES": ImportTypeDef("OPENING_BALANCES", None, [
        ColumnSpec("party_type", "text", True, "party_type", "CUSTOMER or SUPPLIER.", "CUSTOMER"),
        ColumnSpec("party_name", "text", True, "party_name", "Must already exist.", "Ramesh Traders"),
        ColumnSpec("amount", "number", True, "amount", "Opening balance amount (positive).", "50000"),
        ColumnSpec("balance_type", "text", True, "balance_type", "Dr (customer owes us) or Cr (we owe supplier).", "Dr"),
    ]),
    "RECEIPTS": ImportTypeDef("RECEIPTS", "CUSTOMER", [
        ColumnSpec("date", "date", True, "date", "DD-MM-YYYY, on/after 01-04-2026.", "10-04-2026"),
        ColumnSpec("customer_name", "text", True, "party_name", "Must already exist.", "Ramesh Traders"),
        ColumnSpec("amount", "number", True, "amount", "Amount received (positive).", "1180"),
        ColumnSpec("mode", "text", True, "mode", "CASH or BANK.", "BANK"),
        ColumnSpec("bank_account_name", "text", False, "bank_account", "Required when mode is BANK; must already exist.", "HDFC Current"),
        ColumnSpec("reference_no", "text", False, None, "Cheque/UPI reference.", "UPI-12345"),
    ]),
    "PAYMENTS": ImportTypeDef("PAYMENTS", "SUPPLIER", [
        ColumnSpec("date", "date", True, "date", "DD-MM-YYYY, on/after 01-04-2026.", "10-04-2026"),
        ColumnSpec("supplier_name", "text", True, "party_name", "Must already exist.", "Sri Metals"),
        ColumnSpec("amount", "number", True, "amount", "Amount paid (positive).", "4720"),
        ColumnSpec("mode", "text", True, "mode", "CASH or BANK.", "BANK"),
        ColumnSpec("bank_account_name", "text", False, "bank_account", "Required when mode is BANK; must already exist.", "HDFC Current"),
        ColumnSpec("reference_no", "text", False, None, "Cheque/UPI reference.", "CHQ-0091"),
    ]),
}


@dataclass
class ValidationReport:
    """Outcome of validating a file. Holds no DB handle — safe to pass to the UI."""

    import_type: str
    rows_read: int = 0
    errors: list = field(default_factory=list)     # {row_number, message} — block import
    warnings: list = field(default_factory=list)    # {row_number, message} — allow, but show

    def add_error(self, row_number: int, message: str) -> None:
        self.errors.append({"row_number": row_number, "message": message})

    def add_warning(self, row_number: int, message: str) -> None:
        self.warnings.append({"row_number": row_number, "message": message})

    @property
    def is_importable(self) -> bool:
        return len(self.errors) == 0

    @property
    def summary(self) -> dict:
        return {
            "import_type": self.import_type,
            "rows_read": self.rows_read,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "importable": self.is_importable,
        }


class ImportService:
    """Generic import engine: template -> read -> validate -> (import per type)."""

    # --- reading ---------------------------------------------------------

    def read_sheet(self, file_path: str, expected_columns: list[str]) -> list[dict]:
        """Read the first worksheet into a list of {column_name: value} dicts.

        The header row must contain every expected column (order-independent,
        case-insensitive). A missing/misspelled column is a hard error naming it.
        Blank rows and the template's EXAMPLE row are skipped.
        """
        wb = load_workbook(file_path, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header = next(rows_iter)
        except StopIteration:
            raise ValueError("The file is empty.")

        header = [str(h).strip() if h is not None else "" for h in header]
        header_lower = [h.lower() for h in header]
        expected_lower = {c.lower(): c for c in expected_columns}

        missing = [c for c in expected_columns if c.lower() not in header_lower]
        if missing:
            raise ValueError(
                "Missing or misspelled column(s): "
                + ", ".join(missing)
                + ". Expected columns: "
                + ", ".join(expected_columns)
            )

        index_of = {expected_lower[h]: j for j, h in enumerate(header_lower) if h in expected_lower}

        rows: list[dict] = []
        for raw in rows_iter:
            if raw is None or all(v is None or str(v).strip() == "" for v in raw):
                continue  # blank row
            if any(v is not None and EXAMPLE_MARKER in str(v) for v in raw):
                continue  # leftover example row
            rows.append({name: raw[j] if j < len(raw) else None for name, j in index_of.items()})
        return rows

    # --- validation (writes NOTHING) ------------------------------------

    def validate(self, rows: list[dict], import_type: str) -> ValidationReport:
        """Validate parsed rows against the shared rules. Read-only."""
        defn = IMPORT_DEFS[import_type]
        report = ValidationReport(import_type=import_type, rows_read=len(rows))

        session = get_session()
        try:
            checked_refs: set = set()
            for i, row in enumerate(rows):
                row_no = i + 2  # header is row 1; data begins at row 2
                for col in defn.columns:
                    raw = row.get(col.name)
                    blank = raw is None or str(raw).strip() == ""
                    if blank:
                        if col.required:
                            report.add_error(row_no, f"'{col.name}' is required")
                        continue
                    self._validate_cell(session, report, row_no, col, raw, defn, checked_refs)
            self._validate_type_specific(session, report, rows, defn)
        finally:
            session.close()
        return report

    def _validate_type_specific(self, session, report, rows, defn):
        """Rules that depend on more than one cell / on the import type."""
        if defn.key == "OPENING_BALANCES":
            # The party must already exist (we cannot open a balance on a party
            # that has no ledger account).
            for i, row in enumerate(rows):
                row_no = i + 2
                ptype = str(row.get("party_type") or "").strip().upper()
                pname = str(row.get("party_name") or "").strip()
                if not pname or ptype not in ("CUSTOMER", "SUPPLIER"):
                    continue  # already flagged by the per-cell validators
                model = Customer if ptype == "CUSTOMER" else Supplier
                found = (
                    session.query(model.id)
                    .filter(model.name == pname, model.is_deleted == false())
                    .first()
                )
                if found is None:
                    report.add_error(row_no, f"{ptype.capitalize()} '{pname}' does not exist")
        # SALES total cross-check + per-supplier bill_no (PURCHASES) land in H3/H4.

    def _validate_cell(self, session, report, row_no, col, raw, defn, checked_refs):
        role = col.role
        if col.kind == "date" or role == "date":
            parsed = self._parse_date(raw)
            if parsed is None:
                report.add_error(row_no, f"'{col.name}' must be a date as DD-MM-YYYY (got '{raw}')")
            elif parsed < CUTOFF_DATE:
                report.add_error(row_no, f"'{col.name}' {raw} is before the cut-off 01-04-2026")
            return

        if col.kind == "number":
            value = self._parse_number(raw)
            if value is None:
                report.add_error(row_no, f"'{col.name}' must be a number (got '{raw}')")
                return
            if role == "quantity" and value <= 0:
                report.add_error(row_no, f"'{col.name}' must be greater than 0")
            elif role in ("rate", "total", "opening_qty") and value < 0:
                report.add_error(row_no, f"'{col.name}' cannot be negative")
            elif role == "amount" and value <= 0:
                report.add_error(row_no, f"'{col.name}' must be greater than 0")
            return

        text = str(raw).strip()
        if role == "item_code":
            exists = (
                session.query(Item.id)
                .filter(Item.code == text, Item.is_deleted == false())
                .first()
            )
            if exists is None:
                report.add_error(row_no, f"Item code '{text}' does not exist in the Item Master")
        elif role == "party_name":
            model = Customer if defn.party_kind == "CUSTOMER" else Supplier
            if defn.party_kind:
                found = (
                    session.query(model.id)
                    .filter(model.name == text, model.is_deleted == false())
                    .first()
                )
                if found is None:
                    kind = defn.party_kind.lower()
                    report.add_warning(row_no, f"{kind.capitalize()} '{text}' is unknown; it will be created on import")
        elif role == "unique_ref":
            if text not in checked_refs:
                checked_refs.add(text)
                if defn.key == "SALES":
                    dup = (
                        session.query(SalesInvoice.id)
                        .filter(SalesInvoice.invoice_no == text, SalesInvoice.is_deleted == false())
                        .first()
                    )
                    if dup is not None:
                        report.add_error(row_no, f"Invoice number '{text}' already exists in the database")
                # PURCHASES bill_no is unique PER SUPPLIER — handled in H4.
        elif role == "party_type":
            if text.upper() not in ("CUSTOMER", "SUPPLIER"):
                report.add_error(row_no, f"party_type must be CUSTOMER or SUPPLIER (got '{text}')")
        elif role == "balance_type":
            if text.capitalize() not in ("Dr", "Cr"):
                report.add_error(row_no, f"balance_type must be Dr or Cr (got '{text}')")
        elif role == "mode":
            if text.upper() not in ("CASH", "BANK"):
                report.add_error(row_no, f"mode must be CASH or BANK (got '{text}')")

    @staticmethod
    def _parse_date(raw):
        """Return a date, or None if it cannot be parsed unambiguously."""
        if isinstance(raw, datetime):
            return raw.date()
        if isinstance(raw, date_type):
            return raw
        try:
            return datetime.strptime(str(raw).strip(), DATE_FORMAT).date()
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_number(raw):
        if isinstance(raw, (int, float)):
            return float(raw)
        try:
            return float(str(raw).strip().replace(",", ""))
        except (ValueError, TypeError):
            return None

    # --- template generation --------------------------------------------

    def generate_template(self, import_type: str, save_path: str) -> str:
        """Write a correctly-headed .xlsx template for the given import type."""
        defn = IMPORT_DEFS[import_type]
        wb = Workbook()
        ws = wb.active
        ws.title = import_type[:31]

        bold = Font(bold=True)
        example_fill = PatternFill("solid", fgColor="FFF3CD")

        # Header row (+ a NOTE column that carries the delete-me marker).
        for j, col in enumerate(defn.columns, start=1):
            cell = ws.cell(row=1, column=j, value=col.name)
            cell.font = bold
            ws.column_dimensions[get_column_letter(j)].width = max(14, len(col.name) + 2)
        note_col = len(defn.columns) + 1
        note_cell = ws.cell(row=1, column=note_col, value="NOTE")
        note_cell.font = bold
        ws.column_dimensions[get_column_letter(note_col)].width = 22

        # Force date columns to Text so Excel cannot silently reformat them.
        for j, col in enumerate(defn.columns, start=1):
            if col.kind == "date":
                for r in range(2, 500):
                    ws.cell(row=r, column=j).number_format = "@"

        # One example row, clearly marked.
        for j, col in enumerate(defn.columns, start=1):
            c = ws.cell(row=2, column=j, value=col.example)
            c.fill = example_fill
        marker = ws.cell(row=2, column=note_col, value=EXAMPLE_MARKER)
        marker.fill = example_fill
        marker.font = Font(bold=True, color="9C6500")

        ws.freeze_panes = "A2"

        # Instructions sheet.
        info = wb.create_sheet("Instructions")
        info.cell(row=1, column=1, value=f"{import_type} import — column guide").font = bold
        info.cell(row=2, column=1, value="Delete the yellow EXAMPLE row before importing. Dates are DD-MM-YYYY.")
        headers = ["Column", "Required", "Description"]
        for j, h in enumerate(headers, start=1):
            info.cell(row=4, column=j, value=h).font = bold
        for i, col in enumerate(defn.columns, start=5):
            info.cell(row=i, column=1, value=col.name)
            info.cell(row=i, column=2, value="Yes" if col.required else "No")
            info.cell(row=i, column=3, value=col.description)
        for j, width in enumerate((20, 10, 70), start=1):
            info.column_dimensions[get_column_letter(j)].width = width

        wb.save(save_path)
        logger.info("Generated %s template at %s", import_type, save_path)
        return save_path

    # --- import dispatch -------------------------------------------------

    def import_data(self, import_type: str, file_path: str, created_by: str | None) -> ImportLog:
        """Dispatch to the per-type importer (each re-validates first)."""
        if import_type == "OPENING_STOCK":
            return self.import_opening_stock(file_path, created_by)
        if import_type == "OPENING_BALANCES":
            return self.import_opening_balances(file_path, created_by)
        raise NotImplementedError(
            f"{import_type} import is added in a later milestone (H3-H5). "
            "Validation and templates are available now."
        )

    def _guard_importable(self, file_path: str, import_type: str) -> list[dict]:
        """Re-read + re-validate; refuse to import a file with any error."""
        rows = self.read_sheet(file_path, IMPORT_DEFS[import_type].column_names())
        report = self.validate(rows, import_type)
        if not report.is_importable:
            first = report.errors[0]
            raise ValueError(
                f"File has {len(report.errors)} error(s); cannot import. "
                f"First: row {first['row_number']} — {first['message']}"
            )
        return rows

    def import_opening_stock(self, file_path: str, created_by: str | None) -> ImportLog:
        rows = self._guard_importable(file_path, "OPENING_STOCK")
        obs = OpeningBalanceService()
        session = get_session()
        created = 0
        try:
            for row in rows:
                item = (
                    session.query(Item)
                    .filter(Item.code == str(row["item_code"]).strip(), Item.is_deleted == false())
                    .first()
                )
                obs.set_opening_stock(session, item.id, self._parse_number(row["opening_qty"]), created_by)
                created += 1
            log = self._write_log(session, "OPENING_STOCK", file_path, len(rows), created, "IMPORTED")
            return log
        except Exception as exc:
            self._write_log(session, "OPENING_STOCK", file_path, len(rows), created, "FAILED", str(exc))
            raise
        finally:
            session.close()

    def import_opening_balances(self, file_path: str, created_by: str | None) -> ImportLog:
        rows = self._guard_importable(file_path, "OPENING_BALANCES")
        obs = OpeningBalanceService()
        session = get_session()
        created = 0
        try:
            for row in rows:
                ptype = str(row["party_type"]).strip().upper()
                pname = str(row["party_name"]).strip()
                model = Customer if ptype == "CUSTOMER" else Supplier
                party = (
                    session.query(model).filter(model.name == pname, model.is_deleted == false()).first()
                )
                obs.set_party_opening_balance(
                    session, ptype, party.id, self._parse_number(row["amount"]),
                    str(row["balance_type"]).strip(), created_by,
                )
                created += 1
            # NOTE: staging only — the user posts the opening journal separately.
            log = self._write_log(session, "OPENING_BALANCES", file_path, len(rows), created, "IMPORTED")
            return log
        except Exception as exc:
            self._write_log(session, "OPENING_BALANCES", file_path, len(rows), created, "FAILED", str(exc))
            raise
        finally:
            session.close()

    @staticmethod
    def _write_log(session, import_type, file_path, rows_read, created, status, notes=None) -> ImportLog:
        import os

        log = ImportLog(
            file_name=os.path.basename(file_path),
            import_type=import_type,
            rows_read=rows_read,
            records_created=created,
            status=status,
            notes=notes,
        )
        session.add(log)
        session.commit()
        session.refresh(log)
        session.expunge(log)
        return log
