"""Outstanding receivables/payables (module: accounts)."""

from fastapi import APIRouter, Depends

from api.auth import require_permission
from services.accounting_service import AccountingService
from services.permissions import MODULE_ACCOUNTS

router = APIRouter(prefix="/api/outstanding", tags=["outstanding"])


@router.get("/customers", dependencies=[Depends(require_permission(MODULE_ACCOUNTS))])
def outstanding_customers():
    return AccountingService.get_outstanding_customers()


@router.get("/suppliers", dependencies=[Depends(require_permission(MODULE_ACCOUNTS))])
def outstanding_suppliers():
    return AccountingService.get_outstanding_suppliers()
