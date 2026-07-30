"""OCR purchase screen: scan a supplier bill, review the extracted data,
correct it, and save through the EXISTING purchase flow.

This screen subclasses PurchaseScreen so the line-entry table, GST totals and
save all reuse `PurchaseService.create_purchase_invoice()` unchanged (CLAUDE.md:
one save path, no business logic in the UI). OCR only pre-fills the header and
shows the scanned text as a reference — every field stays editable, and the
user confirms before saving (OCR_Instruction.txt: a time-saver, not an
auto-importer).

Findings from the Milestone 21 real-bill test drive the defaults here: amounts
and line items are NOT trusted from OCR (they default to manual entry); the
reliable pre-fills are supplier, GSTIN, invoice number and date.
"""

import logging
from datetime import datetime

from PySide6.QtCore import QDate, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.document_service import DocumentService
from services.session_context import SessionContext
from services.ocr_service import confidence_band
from services.purchase_service import PurchaseService
from ui.purchase import PurchaseScreen

logger = logging.getLogger(__name__)

_BILL_FILTER = "Supplier bills (*.pdf *.jpg *.jpeg *.png)"
_DATE_FORMATS = (
    "%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y",
    "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y",
)


def _parse_ocr_date(raw: str | None) -> QDate | None:
    """Best-effort parse of an OCR date string (e.g. '11-Apr-23') to a QDate."""
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw.strip(), fmt)
            return QDate(parsed.year, parsed.month, parsed.day)
        except ValueError:
            continue
    return None


class _OcrWorker(QThread):
    """Runs OCR on a document off the GUI thread (a scan takes minutes)."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, document_service: DocumentService, document_id: int):
        super().__init__()
        self._document_service = document_service
        self._document_id = document_id

    def run(self):
        try:
            self.done.emit(self._document_service.run_ocr_on_document(self._document_id))
        except Exception as exc:  # keep the UI alive; report the message
            logger.exception("OCR worker failed")
            self.failed.emit(str(exc))


class OCRPurchaseScreen(PurchaseScreen):
    """PurchaseScreen + an OCR upload/review stage bolted on top."""

    def __init__(
        self,
        item_service=None,
        supplier_service=None,
        purchase_service: PurchaseService | None = None,
        document_service: DocumentService | None = None,
    ):
        super().__init__(item_service, supplier_service, purchase_service)
        self.document_service = document_service or DocumentService()
        self._selected_file: str | None = None
        self._current_document_id: int | None = None
        self._worker: _OcrWorker | None = None

        self._build_ocr_ui()
        self.save_button.setText("Save Purchase Invoice")

        # Save stays disabled until supplier + invoice no + at least one line
        # (which yields the total) are present (OCR_Instruction.txt Step 4).
        self.invoice_no_input.textChanged.connect(self._update_save_enabled)
        self._update_save_enabled()

    # --- UI construction -------------------------------------------------

    def _build_ocr_ui(self):
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self.on_browse)
        self.file_label = QLabel("No file selected.")
        self.scan_button = QPushButton("Scan Bill")
        self.scan_button.clicked.connect(self.on_scan)
        self.scan_button.setEnabled(False)

        top_row = QHBoxLayout()
        top_row.addWidget(self.browse_button)
        top_row.addWidget(self.file_label, 1)
        top_row.addWidget(self.scan_button)

        self.status_label = QLabel("")
        self.confidence_label = QLabel("")
        self.warnings_label = QLabel("")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setStyleSheet("color: #8a6d00;")  # amber, like a warning
        self.scanned_amounts_label = QLabel("")
        self.scanned_amounts_label.setWordWrap(True)
        self.scanned_amounts_label.setStyleSheet("color: #555;")

        self.raw_text_view = QPlainTextEdit()
        self.raw_text_view.setReadOnly(True)
        self.raw_text_view.setPlaceholderText(
            "Scanned text will appear here as a reference while you check the form."
        )
        self.raw_text_view.setMaximumHeight(160)

        ocr_layout = QVBoxLayout()
        ocr_layout.addLayout(top_row)
        ocr_layout.addWidget(self.status_label)
        ocr_layout.addWidget(self.confidence_label)
        ocr_layout.addWidget(self.warnings_label)
        ocr_layout.addWidget(QLabel("Scanned amounts (reference only — enter line items below):"))
        ocr_layout.addWidget(self.scanned_amounts_label)
        ocr_layout.addWidget(self.raw_text_view)

        ocr_box = QGroupBox("Scan Supplier Bill (OCR)")
        ocr_box.setLayout(ocr_layout)

        # Insert the OCR box at the very top of the inherited layout.
        self.layout().insertWidget(0, ocr_box)

    # --- Stage 1: upload + scan -----------------------------------------

    def on_browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select supplier bill", "", _BILL_FILTER)
        if not path:
            return
        self._selected_file = path
        self.file_label.setText(path)
        self.scan_button.setEnabled(True)

    def on_scan(self):
        if not self._selected_file:
            return
        try:
            document = self.document_service.save_document(
                self._selected_file, created_by=SessionContext.get_username()
            )
        except Exception as exc:
            logger.exception("Failed to save document before OCR")
            self.status_label.setText(f"Could not store the file: {exc}")
            return

        self._current_document_id = document.id
        self._set_scanning(True)
        self.status_label.setText("Scanning… this can take a few minutes. Please wait.")

        self._worker = _OcrWorker(self.document_service, document.id)
        self._worker.done.connect(self._on_ocr_done)
        self._worker.failed.connect(self._on_ocr_failed)
        self._worker.start()

    def _set_scanning(self, scanning: bool):
        self.browse_button.setEnabled(not scanning)
        self.scan_button.setEnabled(not scanning and self._selected_file is not None)

    # --- Stage 2: review (populate from OCR) ----------------------------

    def _on_ocr_done(self, result: dict):
        self._set_scanning(False)
        self.status_label.setText("Scan complete. Review and correct every field before saving.")

        self.raw_text_view.setPlainText(result.get("raw_text") or "")
        self.confidence_label.setText(
            f"Confidence: {confidence_band(result.get('confidence', 0.0))}"
        )
        warnings = result.get("warnings") or []
        self.warnings_label.setText(
            "⚠ " + "  •  ".join(warnings) if warnings else ""
        )
        self._show_scanned_amounts(result)

        if result.get("invoice_number"):
            self.invoice_no_input.setText(result["invoice_number"])
        parsed_date = _parse_ocr_date(result.get("invoice_date"))
        if parsed_date is not None:
            self.date_input.setDate(parsed_date)

        self._prefill_supplier(result)
        self._update_save_enabled()

    def _on_ocr_failed(self, message: str):
        self._set_scanning(False)
        self.status_label.setText(f"OCR failed: {message}. You can still enter the bill manually.")

    def _show_scanned_amounts(self, result: dict):
        def fmt(value):
            return "-" if value is None else f"{value:,.2f}"

        self.scanned_amounts_label.setText(
            f"Taxable {fmt(result.get('taxable_amount'))} | "
            f"CGST {fmt(result.get('cgst'))} | SGST {fmt(result.get('sgst'))} | "
            f"IGST {fmt(result.get('igst'))} | Total {fmt(result.get('total_amount'))}"
        )

    def _prefill_supplier(self, result: dict):
        """Select a matching supplier by GSTIN/name, else seed the New Supplier box."""
        gstin = (result.get("supplier_gstin") or "").strip().upper()
        name = (result.get("supplier_name") or "").strip()

        for index in range(self.supplier_combo.count()):
            data = self.supplier_combo.itemData(index)
            if not data:
                continue
            data_gstin = (data.get("gstin") or "").strip().upper()
            if gstin and data_gstin and gstin == data_gstin:
                self.supplier_combo.setCurrentIndex(index)
                return
            if name and name.lower() in (data.get("name") or "").lower():
                self.supplier_combo.setCurrentIndex(index)
                return

        # No match: pre-fill the inline "New Supplier" fields so the user can
        # add it with one click (base PurchaseScreen.on_add_supplier).
        if name:
            self.new_supplier_name.setText(name)
        if gstin:
            self.new_supplier_gstin.setText(gstin)

    # --- Save-enable + document linking ---------------------------------

    def refresh_lines_table(self):
        super().refresh_lines_table()
        self._update_save_enabled()

    def _update_save_enabled(self):
        has_supplier = self.supplier_combo.currentData() is not None
        has_invoice_no = bool(self.invoice_no_input.text().strip())
        has_lines = bool(self.lines)
        self.save_button.setEnabled(has_supplier and has_invoice_no and has_lines)

    def _after_save(self, invoice):
        """Link the scanned document to the invoice the base class just saved."""
        if self._current_document_id is not None:
            try:
                self.document_service.link_to_purchase_invoice(
                    self._current_document_id, invoice.id
                )
            except Exception:
                logger.exception("Failed to link document to invoice")
        self._reset_ocr_state()

    def _reset_ocr_state(self):
        self._selected_file = None
        self._current_document_id = None
        self.file_label.setText("No file selected.")
        self.scan_button.setEnabled(False)
        self.status_label.setText("")
        self.confidence_label.setText("")
        self.warnings_label.setText("")
        self.scanned_amounts_label.setText("")
        self.raw_text_view.clear()


class DocumentHistoryScreen(QWidget):
    """Read-only list of scanned documents and their OCR/link status."""

    COLUMNS = ["File", "Uploaded", "Type", "OCR Status", "Confidence", "Linked Invoice #"]

    def __init__(self, document_service: DocumentService | None = None):
        super().__init__()
        self.document_service = document_service or DocumentService()

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        layout = QVBoxLayout()
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.table)
        self.setLayout(layout)

        self.refresh()

    def refresh(self):
        documents = self.document_service.list_documents()
        self.table.setRowCount(len(documents))
        for row, doc in enumerate(documents):
            uploaded = doc["upload_date"]
            uploaded_text = uploaded.strftime("%Y-%m-%d %H:%M") if uploaded else "-"
            confidence = doc["ocr_confidence"]
            confidence_text = "-" if confidence is None else f"{confidence:.2f}"
            linked = doc["linked_purchase_invoice_id"]
            values = [
                doc["file_name"],
                uploaded_text,
                doc["document_type"],
                doc["ocr_status"],
                confidence_text,
                "-" if linked is None else str(linked),
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))
