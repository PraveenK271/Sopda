"""Business logic for stored documents (scanned supplier bills).

Handles copying an uploaded file into the project's ``documents/`` folder,
recording it, running OCR on it (via :class:`OCRService`), and linking a saved
document to the purchase invoice it produced. Per CLAUDE.md all this logic
lives here, not in the UI.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path

from database import get_session
from models import Document
from services.ocr_service import OCRService

logger = logging.getLogger(__name__)

# documents/ lives next to the app package (gemini_erp/documents), alongside
# the SQLite db and gemini_erp/output.
DOCUMENTS_DIR = Path(__file__).resolve().parents[1] / "documents"


class DocumentService:
    """Store uploaded bills, run OCR on them, and link them to invoices."""

    def __init__(self, ocr_service: OCRService | None = None):
        # Injectable so tests can pass a fake OCR engine.
        self._ocr_service = ocr_service or OCRService()

    def save_document(
        self,
        file_path: str,
        document_type: str = "PURCHASE_BILL",
        created_by: str | None = None,
    ) -> Document:
        """Copy the file into documents/ under a unique name and record it.

        Does NOT run OCR — that is triggered separately via
        :meth:`run_ocr_on_document`.
        """
        source = Path(file_path)
        if not source.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        # timestamp prefix keeps names unique even for repeat uploads of a file.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        stored_name = f"{stamp}_{source.name}"
        stored_path = DOCUMENTS_DIR / stored_name
        shutil.copy2(source, stored_path)

        session = get_session()
        try:
            document = Document(
                file_name=source.name,
                file_path=str(stored_path),
                document_type=document_type,
                ocr_status="PENDING",
                created_by=created_by,
            )
            session.add(document)
            session.commit()
            session.refresh(document)
            session.expunge(document)  # usable after the session closes
            logger.info("Saved document %s as %s", source.name, stored_name)
            return document
        except Exception:
            session.rollback()
            logger.exception("Failed to save document %s", file_path)
            raise
        finally:
            session.close()

    def run_ocr_on_document(self, document_id: int) -> dict:
        """Run OCR on a stored document, persist the result, return the dict.

        Updates ocr_status ('DONE' if text was extracted, else 'FAILED'),
        ocr_raw_text and ocr_confidence on the row.
        """
        session = get_session()
        try:
            document = session.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")

            result = self._ocr_service.extract_from_file(document.file_path)

            document.ocr_raw_text = result["raw_text"]
            document.ocr_confidence = result["confidence"]
            document.ocr_status = "DONE" if result["raw_text"].strip() else "FAILED"
            session.commit()
            logger.info(
                "OCR on document %s -> %s (confidence %.2f)",
                document_id,
                document.ocr_status,
                result["confidence"],
            )
            return result
        except Exception:
            session.rollback()
            logger.exception("Failed to run OCR on document %s", document_id)
            raise
        finally:
            session.close()

    def link_to_purchase_invoice(
        self, document_id: int, purchase_invoice_id: int
    ) -> None:
        """Connect a scanned document to the purchase invoice it produced."""
        session = get_session()
        try:
            document = session.get(Document, document_id)
            if document is None:
                raise ValueError(f"Document {document_id} not found")
            document.linked_purchase_invoice_id = purchase_invoice_id
            session.commit()
            logger.info(
                "Linked document %s to purchase invoice %s",
                document_id,
                purchase_invoice_id,
            )
        except Exception:
            session.rollback()
            logger.exception("Failed to link document %s", document_id)
            raise
        finally:
            session.close()

    def list_documents(self, document_type: str | None = None) -> list[dict]:
        """List stored documents (newest first) as plain dicts for the UI.

        Returns dicts rather than ORM objects (mirrors the other services) so
        callers are not tied to an open session.
        """
        session = get_session()
        try:
            query = session.query(Document).filter(Document.is_deleted.is_(False))
            if document_type is not None:
                query = query.filter(Document.document_type == document_type)
            documents = query.order_by(Document.id.desc()).all()
            return [
                {
                    "id": d.id,
                    "file_name": d.file_name,
                    "file_path": d.file_path,
                    "upload_date": d.upload_date,
                    "document_type": d.document_type,
                    "ocr_status": d.ocr_status,
                    "ocr_confidence": d.ocr_confidence,
                    "linked_purchase_invoice_id": d.linked_purchase_invoice_id,
                }
                for d in documents
            ]
        except Exception:
            logger.exception("Failed to list documents")
            raise
        finally:
            session.close()
