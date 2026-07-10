"""OCR service — the app's single bridge to the OCR engine.

PaddlePaddle has no wheels for the app's Python 3.14 runtime, so the actual OCR
runs in a separate Python 3.13 venv (``venv_ocr``) via ``ocr_runner.py`` — the
only file that imports PaddleOCR. This module:

  * invokes that runner as a subprocess (``extract_from_file``),
  * parses the raw OCR text into structured invoice fields with regex
    (``_parse_results``) — pure Python, so it is unit-tested on the main
    interpreter by ``check_ocr_service.py``,
  * returns one standard dict that every caller (the UI) receives, regardless
    of which engine produced it.

Per ``CLAUDE.md`` / ``OCR_Instruction.txt``: OCR is a time-saver, not an
auto-importer. Output is a suggestion the user confirms before anything is
saved. A field that cannot be extracted is ``None`` plus a warning — this
service never raises for a missing field, and never crashes the UI.
"""

import json
import logging
import re
import subprocess
import sys
from pathlib import Path

from database import get_app_root
from reports.company_info import COMPANY_GSTIN

logger = logging.getLogger(__name__)


def _resolve_ocr_paths() -> tuple[Path, Path]:
    """Locate the 3.13 OCR interpreter and runner script, source or packaged.

    The OCR engine can't be frozen into the exe (PaddlePaddle has no 3.14
    wheels), so it always runs as a loose script under its own 3.13 venv:

      * source:   <repo>/venv_ocr + gemini_erp/services/ocr_runner.py (unchanged
                  dev layout).
      * packaged: a self-contained ocr_worker/ folder next to the exe, holding
                  ocr_runner.py and a venv_ocr the user creates once (see
                  DISTRIBUTION_README). Graceful degradation in extract_from_file
                  handles the venv not being set up yet.
    """
    if getattr(sys, "frozen", False):
        worker = Path(get_app_root()) / "ocr_worker"
        return worker / "venv_ocr" / "Scripts" / "python.exe", worker / "ocr_runner.py"
    project_root = Path(__file__).resolve().parents[2]
    return (
        project_root / "venv_ocr" / "Scripts" / "python.exe",
        Path(__file__).resolve().parent / "ocr_runner.py",
    )


_OCR_PYTHON, _OCR_RUNNER = _resolve_ocr_paths()

_OCR_TIMEOUT_SECONDS = 600  # real bills take ~150s; first run also downloads models

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

# Standard 15-char GSTIN format (from OCR_Instruction.txt).
_GSTIN_RE = re.compile(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}")
# A "money-like" amount: Indian/Western thous-grouped (1,50,975.00 / 1,234.56)
# or a plain decimal (90.00). Deliberately excludes bare integers like a "13"
# quantity so amounts aren't confused with qty columns in a bill table.
_MONEY_RE = re.compile(r"\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+\.\d{2}")
# Any number token (used only on a label's own line, where a bare integer is
# the value, e.g. "₹ 1234").
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# A rate token like "9%", "18.00 %" — stripped from a label line so it is not
# mistaken for the amount.
_RATE_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
# Dates: dd/mm/yyyy, dd-mm-yy, dd.mm.yyyy AND dd-Mon-yy (11-Apr-23) — real bills
# use both. Month is 1-2 digits or a 3-9 letter name.
_DATE_RE = re.compile(r"\b\d{1,2}[/.\-](?:\d{1,2}|[A-Za-z]{3,9})[/.\-]\d{2,4}\b")

_INVOICE_KEYWORDS = (
    "invoice no",
    "bill no",
    "inv no",
    "invoice #",
    "bill number",
    "invoice number",
)


def _empty_result() -> dict:
    """The standard output dict shape every caller receives."""
    return {
        "supplier_name": None,
        "invoice_number": None,
        "invoice_date": None,  # raw string, user confirms format
        "supplier_gstin": None,
        "line_items": [],
        "taxable_amount": None,
        "cgst": None,
        "sgst": None,
        "igst": None,
        "total_amount": None,
        "raw_text": "",
        "confidence": 0.0,
        "warnings": [],
    }


def _clean_amount(text: str):
    """Strip currency/commas/spaces and parse to float, or None."""
    cleaned = text.replace("₹", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _find_amount(lines: list[str], keywords: list[str], lookahead: int = 3):
    """Find the money value for a labelled amount, tolerating tabular layouts.

    Real GST bills put the label ("CGST @ 9%", "Grand Total") and its value in
    separate table cells, which OCR emits as separate lines. So for a line
    matching a keyword we search that line AND the next few lines for the first
    *money-like* token (``_MONEY_RE`` skips bare integers such as quantity
    columns). On a single-line label like ``CGST 9% 90.00`` it matches on the
    same line.
    """
    for i, line in enumerate(lines):
        if not any(kw in line.lower() for kw in keywords):
            continue
        # On the label's own line, drop rate tokens ("9%") first, then take a
        # money-like value, else a bare number (handles "₹ 1234").
        label = _RATE_RE.sub(" ", line)
        match = _MONEY_RE.search(label)
        if match:
            return _clean_amount(match.group(0))
        numbers = _NUMBER_RE.findall(label)
        if numbers:
            return _clean_amount(numbers[-1])
        # Value sits in a separate cell -> scan the next lines, money-like only
        # so quantity integers in adjacent columns are skipped.
        for j in range(i + 1, min(i + 1 + lookahead, len(lines))):
            match = _MONEY_RE.search(lines[j])
            if match:
                return _clean_amount(match.group(0))
    return None


def _find_after_keyword(lines: list[str], keywords: tuple[str, ...]):
    """Return the first token after any keyword (for invoice numbers)."""
    for line in lines:
        low = line.lower()
        for kw in keywords:
            idx = low.find(kw)
            if idx != -1:
                rest = line[idx + len(kw):].lstrip(" :#.-\t")
                parts = rest.split()
                if parts:
                    return parts[0]
    return None


def _find_date(lines: list[str]):
    """Find the invoice date, avoiding payment/order/due dates on the same bill.

    Preference order: a line naming the *invoice* date, then any 'date'/'dt'
    line that is not a payment/order/due/delivery date, then any date at all.
    """
    _excluded = ("pay", "due", "order", "d c", "delivery", "ack")

    for line in lines:
        low = line.lower()
        if "invoice date" in low or ("invoice" in low and "date" in low):
            match = _DATE_RE.search(line)
            if match:
                return match.group(0)
    for line in lines:
        low = line.lower()
        if ("date" in low or re.search(r"\bdt\b", low)) and not any(
            x in low for x in _excluded
        ):
            match = _DATE_RE.search(line)
            if match:
                return match.group(0)
    for line in lines:
        match = _DATE_RE.search(line)
        if match:
            return match.group(0)
    return None


def _pick_supplier_name(lines: list[str]):
    """First line that looks like a name, skipping logo glyphs / header text."""
    for line in lines:
        if sum(c.isascii() and c.isalpha() for c in line) >= 4 and (
            "tax invoice" not in line.lower()
        ):
            return line
    return lines[0] if lines else None


def confidence_band(confidence: float) -> str:
    """Human label for the OCR confidence (used by the review UI, Milestone 23)."""
    if confidence >= 0.85:
        return "High confidence"
    if confidence >= 0.60:
        return "Medium — please review carefully"
    return "Low — most fields need manual check"


class OCRService:
    """Extract structured invoice data from a scanned supplier bill.

    The engine itself lives in the ``venv_ocr`` subprocess; this class is the
    only bridge to it plus the regex parsing layer.
    """

    def extract_from_file(self, file_path: str) -> dict:
        """Run OCR on a PDF/JPG/JPEG/PNG and return the standard dict.

        Never raises: on any failure the standard dict is returned with the
        problem recorded in ``warnings`` and ``confidence`` at 0.0.
        """
        result = _empty_result()
        try:
            path = Path(file_path)
            if not path.is_file():
                result["warnings"].append(f"File not found: {file_path}")
                return result
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                result["warnings"].append(f"Unsupported file type: {path.suffix}")
                return result

            ocr = self._run_ocr(path)
            result["raw_text"] = ocr["raw_text"]
            result["confidence"] = ocr["confidence"]
            result["warnings"].extend(ocr["warnings"])

            if ocr["raw_text"].strip():
                parsed = self._parse_results(ocr["raw_text"])
                for key in (
                    "supplier_name",
                    "invoice_number",
                    "invoice_date",
                    "supplier_gstin",
                    "taxable_amount",
                    "cgst",
                    "sgst",
                    "igst",
                    "total_amount",
                    "line_items",
                ):
                    result[key] = parsed[key]
                result["warnings"].extend(parsed["warnings"])
            return result
        except Exception as exc:  # never crash the UI
            logger.exception("OCR failed for %s", file_path)
            result["warnings"].append(f"OCR failed: {exc}")
            result["confidence"] = 0.0
            return result

    def _run_ocr(self, path: Path) -> dict:
        """Invoke the 3.13 OCR runner subprocess and return raw text + confidence."""
        if not _OCR_PYTHON.exists():
            raise RuntimeError(
                f"OCR venv not found at {_OCR_PYTHON}. "
                "Create it and install requirements-ocr.txt (see README.md)."
            )
        proc = subprocess.run(
            [str(_OCR_PYTHON), str(_OCR_RUNNER), str(path)],
            capture_output=True,
            text=True,
            timeout=_OCR_TIMEOUT_SECONDS,
        )
        output = proc.stdout.strip()
        if not output:
            raise RuntimeError(
                f"OCR runner produced no output (stderr tail: {proc.stderr[-500:]})"
            )
        # stdout carries only the JSON line, but be defensive and take the last.
        data = json.loads(output.splitlines()[-1])
        return {
            "raw_text": data.get("raw_text", "") or "",
            "confidence": float(data.get("confidence", 0.0) or 0.0),
            "warnings": list(data.get("warnings", [])),
        }

    def _parse_results(self, raw_text: str) -> dict:
        """Extract structured fields from raw OCR text with regex (paddle-free).

        Handles common Indian supplier-bill layouts. Any field the regex cannot
        find is left ``None`` with a warning — values are never invented.
        """
        result = _empty_result()
        result["raw_text"] = raw_text
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

        # Supplier GSTIN: first valid GSTIN that is not our own.
        supplier_gstin = None
        for gstin in _GSTIN_RE.findall(raw_text.upper()):
            if gstin != COMPANY_GSTIN.upper():
                supplier_gstin = gstin
                break
        result["supplier_gstin"] = supplier_gstin
        if supplier_gstin is None:
            result["warnings"].append("Could not detect supplier GSTIN.")

        invoice_number = _find_after_keyword(lines, _INVOICE_KEYWORDS)
        result["invoice_number"] = invoice_number
        if invoice_number is None:
            result["warnings"].append("Could not detect invoice number.")

        invoice_date = _find_date(lines)
        result["invoice_date"] = invoice_date
        if invoice_date is None:
            result["warnings"].append("Could not detect invoice date.")

        # Supplier name: first "word-like" line at the top, skipping logo/QR
        # glyphs and the "Tax Invoice" header (real bills often start with those).
        result["supplier_name"] = _pick_supplier_name(lines)
        if result["supplier_name"] is None:
            result["warnings"].append("Could not detect supplier name.")

        result["taxable_amount"] = _find_amount(lines, ["taxable"])
        result["cgst"] = _find_amount(lines, ["cgst"])
        result["sgst"] = _find_amount(lines, ["sgst"])
        # bills label inter-state tax "IGST" or "Integrated Tax".
        result["igst"] = _find_amount(lines, ["igst", "integrated tax"])
        result["total_amount"] = _find_amount(lines, ["grand total", "total"])
        if result["total_amount"] is None:
            result["warnings"].append("Could not detect total amount.")

        # Line items are deliberately NOT guessed: wrong quantities/rates would
        # corrupt stock (OCR_Instruction.txt 2e). The user enters them from the
        # raw-text reference in the review screen.
        result["line_items"] = []
        result["warnings"].append(
            "Line items not auto-extracted — please enter/verify manually "
            "using the scanned text as reference."
        )
        return result
