"""Recent sales invoices (module: sales_log)."""

from fastapi import APIRouter, Depends, Query

from api.auth import require_permission
from services.permissions import MODULE_SALES_LOG
from services.sales_service import SalesService

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


@router.get("/recent", dependencies=[Depends(require_permission(MODULE_SALES_LOG))])
def recent_invoices(limit: int = Query(default=20, ge=1, le=200)):
    # list_invoices() is already newest-first. Cancelled invoices are kept (a
    # document list shows that a number exists and is void) and carry
    # status == "CANCELLED" for the client to mark.
    return SalesService().list_invoices()[:limit]
