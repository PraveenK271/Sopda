"""Milestone 23 check: OCR review screen + Document History (headless).

Runs a real QApplication offscreen (no display, no clicking) and exercises the
whole screen path WITHOUT the ~4-min OCR engine: it stores a document, calls the
screen's OCR-done handler with a canned result, adds a line item, and saves —
then asserts a purchase invoice was created through the EXISTING
PurchaseService and the scanned document was linked to it.

Mirrors the temporary-headless-test approach noted for Milestones 4 and 8.
"""

import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from database import get_session  # noqa: E402
from models import Document  # noqa: E402
from services.document_service import DocumentService  # noqa: E402
from services.item_service import ItemService  # noqa: E402
from services.purchase_service import PurchaseService  # noqa: E402
from services.supplier_service import SupplierService  # noqa: E402
from ui.ocr_purchase import DocumentHistoryScreen, OCRPurchaseScreen, _parse_ocr_date  # noqa: E402

SAMPLE_FILE = (
    Path(__file__).resolve().parents[1]
    / "Samples_TestOCR"
    / "WhatsApp Image 2026-07-09 at 15.05.17.jpeg"
)

# Silence modal dialogs so the headless run does not block.
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)


def _ensure_fixtures():
    """A supplier and an item to build a line from; return (supplier, item_id)."""
    supplier_service = SupplierService()
    suppliers = supplier_service.list_suppliers()
    supplier = next((s for s in suppliers if s["name"] == "OCR Check Supplier"), None)
    if supplier is None:
        supplier_service.add_supplier(
            name="OCR Check Supplier", gstin="37AACCV3469M1ZQ",
            address="Guntakal", state="Andhra Pradesh",
        )
        supplier = next(
            s for s in supplier_service.list_suppliers() if s["name"] == "OCR Check Supplier"
        )

    item_service = ItemService()
    items = item_service.list_items()
    item = next((i for i in items if i["code"] == "OCRCHK1"), None)
    if item is None:
        created = item_service.add_item(
            code="OCRCHK1", name="OCR Check Item", hsn_code="39172310",
            gst_rate=18.0, unit="Nos", opening_stock=0, reorder_level=0,
        )
        item_id = created.id
    else:
        item_id = item["id"]
    return supplier, item_id


def check_date_parsing():
    assert _parse_ocr_date("11-Apr-23") is not None
    assert _parse_ocr_date("15/04/2024") is not None
    assert _parse_ocr_date("garbage") is None
    print("[1] _parse_ocr_date: alpha-month + numeric parse, garbage -> None OK")


def check_review_and_save(app):
    supplier, item_id = _ensure_fixtures()

    doc_service = DocumentService()
    document = doc_service.save_document(str(SAMPLE_FILE), created_by="check_m23")

    screen = OCRPurchaseScreen(document_service=doc_service)
    screen.refresh_lookups()

    # Save must be disabled before anything is filled in.
    assert not screen.save_button.isEnabled(), "save should start disabled"

    # Simulate OCR completing with a canned result (no real engine).
    screen._current_document_id = document.id
    invoice_no = f"CHK-M23-{datetime.now():%H%M%S}"
    screen._on_ocr_done({
        "raw_text": "VASAVI PIPES PRIVATE LIMITED\nInvoice No: X\nGrand Total 45,039.00",
        "confidence": 0.9,
        "warnings": ["Line items not auto-extracted — please enter/verify manually."],
        "supplier_name": "OCR Check Supplier",
        "supplier_gstin": "37AACCV3469M1ZQ",
        "invoice_number": invoice_no,
        "invoice_date": "11-Apr-23",
        "taxable_amount": None, "cgst": None, "sgst": None, "igst": None,
        "total_amount": 45039.00,
    })

    # Header pre-filled + supplier matched by GSTIN.
    assert screen.invoice_no_input.text() == invoice_no, screen.invoice_no_input.text()
    assert screen.raw_text_view.toPlainText().startswith("VASAVI"), "raw text not shown"
    assert screen.supplier_combo.currentData() is not None
    assert screen.supplier_combo.currentData()["id"] == supplier["id"], "supplier not matched"

    # Still no line item -> save stays disabled (amounts/lines are manual).
    assert not screen.save_button.isEnabled(), "save should need a line item"

    # Add a line the same way the UI does, then save.
    for index in range(screen.item_combo.count()):
        if screen.item_combo.itemData(index)["id"] == item_id:
            screen.item_combo.setCurrentIndex(index)
            break
    screen.qty_input.setText("2")
    screen.rate_input.setText("100")
    screen.on_add_line()
    assert screen.lines, "line not added"
    assert screen.save_button.isEnabled(), "save should now be enabled"

    screen.on_save_purchase()

    # A purchase invoice was created via the existing service...
    invoices = PurchaseService().list_purchase_invoices()
    saved = next((inv for inv in invoices if inv["invoice_no"] == invoice_no), None)
    assert saved is not None, "purchase invoice was not created"

    # ...and the scanned document is linked to it.
    session = get_session()
    try:
        refreshed = session.get(Document, document.id)
        assert refreshed.linked_purchase_invoice_id == saved["id"], (
            refreshed.linked_purchase_invoice_id, saved["id"]
        )
    finally:
        session.close()
    print(f"[2] review->save: invoice {invoice_no} created via PurchaseService and document linked OK")

    # OCR state reset after save.
    assert screen._current_document_id is None, "OCR state should reset after save"
    print("[3] OCR state reset after save OK")


def check_history(app):
    history = DocumentHistoryScreen()
    history.refresh()
    assert history.table.rowCount() >= 1, "document history should list saved documents"
    print(f"[4] Document History: {history.table.rowCount()} row(s) listed OK")


def main():
    if not SAMPLE_FILE.is_file():
        raise SystemExit(f"Sample file missing: {SAMPLE_FILE}")
    app = QApplication.instance() or QApplication([])
    check_date_parsing()
    check_review_and_save(app)
    check_history(app)
    print("\nAll Milestone 23 checks passed.")


if __name__ == "__main__":
    main()
