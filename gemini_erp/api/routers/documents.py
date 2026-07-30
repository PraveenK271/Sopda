"""Scanned documents: list + approve/reject (module: documents).

M29c — the mobile companion's single WRITE action. A manager reviews a scanned
supplier bill and approves or rejects it; the sign-off records who and when.
Creating the purchase invoice from the bill stays an interactive desktop step.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.auth import require_permission
from models import User
from services.document_service import DocumentService
from services.permissions import MODULE_DOCUMENTS

router = APIRouter(prefix="/api/documents", tags=["documents"])
_documents = DocumentService()


class ApprovalBody(BaseModel):
    note: str | None = None


@router.get("", dependencies=[Depends(require_permission(MODULE_DOCUMENTS))])
def list_documents(approval_status: str | None = None):
    """All stored documents (newest first); optional ?approval_status= filter."""
    docs = _documents.list_documents()
    if approval_status:
        wanted = approval_status.upper()
        docs = [d for d in docs if d["approval_status"] == wanted]
    return docs


def _decide(document_id: int, decision: str, body: ApprovalBody | None, user: User) -> dict:
    note = body.note if body else None
    try:
        return _documents.set_approval(
            document_id, decision, approved_by=user.username, note=note
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


@router.post("/{document_id}/approve")
def approve(
    document_id: int,
    body: ApprovalBody | None = None,
    user: User = Depends(require_permission(MODULE_DOCUMENTS)),
):
    return _decide(document_id, "APPROVED", body, user)


@router.post("/{document_id}/reject")
def reject(
    document_id: int,
    body: ApprovalBody | None = None,
    user: User = Depends(require_permission(MODULE_DOCUMENTS)),
):
    return _decide(document_id, "REJECTED", body, user)
