"""Milestone 22 check: Document storage (model + DocumentService).

Uses a FAKE OCR engine (DocumentService accepts an injected ocr_service) so the
check is fast and does not spin up the real ~4-minute PaddleOCR subprocess —
Milestone 21 already verified the real engine.

Covers:
  * save_document() copies the file into documents/ under a unique name and
    creates a PENDING row
  * run_ocr_on_document() updates status/raw_text/confidence (DONE when text is
    extracted, FAILED when not)
  * link_to_purchase_invoice() sets the FK
  * list_documents() returns the saved document
"""

from pathlib import Path

from database import get_session
from models import Document, PurchaseInvoice
from services.document_service import DOCUMENTS_DIR, DocumentService

SAMPLE_FILE = (
    Path(__file__).resolve().parents[1]
    / "Samples_TestOCR"
    / "WhatsApp Image 2026-07-09 at 15.05.17.jpeg"
)


class _FakeOCR:
    """Stand-in OCR engine returning a canned standard dict."""

    def __init__(self, raw_text: str, confidence: float):
        self._raw_text = raw_text
        self._confidence = confidence

    def extract_from_file(self, file_path: str) -> dict:
        return {"raw_text": self._raw_text, "confidence": self._confidence, "warnings": []}


def check_save(service):
    doc = service.save_document(str(SAMPLE_FILE), created_by="check_m22")
    assert doc.id is not None
    assert doc.ocr_status == "PENDING", doc.ocr_status
    stored = Path(doc.file_path)
    assert stored.exists(), stored
    assert stored.parent == DOCUMENTS_DIR, stored.parent
    assert stored.name.endswith(SAMPLE_FILE.name), stored.name
    assert stored.name != SAMPLE_FILE.name, "stored name should be unique/prefixed"
    print(f"[1] save_document: copied to {stored.name}, row PENDING OK")
    return doc.id


def check_ocr_done(document_id):
    service = DocumentService(ocr_service=_FakeOCR("VASAVI PIPES ... total 45,039.00", 0.9))
    result = service.run_ocr_on_document(document_id)
    assert result["confidence"] == 0.9
    session = get_session()
    try:
        doc = session.get(Document, document_id)
        assert doc.ocr_status == "DONE", doc.ocr_status
        assert doc.ocr_confidence == 0.9, doc.ocr_confidence
        assert "VASAVI" in (doc.ocr_raw_text or ""), doc.ocr_raw_text
    finally:
        session.close()
    print("[2] run_ocr_on_document (text found): status DONE, fields stored OK")


def check_ocr_failed(document_id):
    service = DocumentService(ocr_service=_FakeOCR("", 0.0))
    service.run_ocr_on_document(document_id)
    session = get_session()
    try:
        doc = session.get(Document, document_id)
        assert doc.ocr_status == "FAILED", doc.ocr_status
    finally:
        session.close()
    print("[3] run_ocr_on_document (no text): status FAILED OK")


def check_link(service, document_id):
    session = get_session()
    try:
        invoice = session.query(PurchaseInvoice).order_by(PurchaseInvoice.id).first()
    finally:
        session.close()
    if invoice is None:
        print("[4] link_to_purchase_invoice: SKIPPED (no purchase invoice in db)")
        return
    service.link_to_purchase_invoice(document_id, invoice.id)
    session = get_session()
    try:
        doc = session.get(Document, document_id)
        assert doc.linked_purchase_invoice_id == invoice.id, doc.linked_purchase_invoice_id
    finally:
        session.close()
    print(f"[4] link_to_purchase_invoice: linked to invoice {invoice.id} OK")


def check_list(service, document_id):
    docs = service.list_documents(document_type="PURCHASE_BILL")
    assert any(d["id"] == document_id for d in docs), "saved doc not in list"
    print(f"[5] list_documents: {len(docs)} purchase-bill document(s), saved one present OK")


def main():
    if not SAMPLE_FILE.is_file():
        raise SystemExit(f"Sample file missing: {SAMPLE_FILE}")
    service = DocumentService(ocr_service=_FakeOCR("dummy", 0.5))
    document_id = check_save(service)
    check_ocr_done(document_id)
    check_ocr_failed(document_id)
    check_link(service, document_id)
    check_list(service, document_id)
    print("\nAll Milestone 22 checks passed.")


if __name__ == "__main__":
    main()
