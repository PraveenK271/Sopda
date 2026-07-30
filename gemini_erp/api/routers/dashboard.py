"""Home dashboard — a per-role summary.

Requires only authentication; each metric is included ONLY if the user's role
permits the underlying module (so a Sales User never sees receivables). A
disallowed metric is null, not omitted, so the PWA can render a stable layout.
"""

from datetime import date

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from models import User
from services.accounting_service import AccountingService
from services.auth_service import AuthService
from services.item_service import ItemService
from services.permissions import MODULE_ACCOUNTS, MODULE_ITEMS, MODULE_SALES_LOG
from services.sales_service import SalesService

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(user: User = Depends(get_current_user)):
    today = date.today()
    result = {
        "today": today.isoformat(),
        "sales_today": None,
        "receivable_total": None,
        "payable_total": None,
        "low_stock_count": None,
    }

    if AuthService.has_permission(user, MODULE_SALES_LOG):
        todays = [inv for inv in SalesService().list_invoices() if inv["date"] == today]
        result["sales_today"] = {
            "count": len(todays),
            "total": round(sum(inv["total"] for inv in todays), 2),
        }

    if AuthService.has_permission(user, MODULE_ACCOUNTS):
        result["receivable_total"] = round(
            sum(r["outstanding"] for r in AccountingService.get_outstanding_customers()), 2
        )
        result["payable_total"] = round(
            sum(r["outstanding"] for r in AccountingService.get_outstanding_suppliers()), 2
        )

    if AuthService.has_permission(user, MODULE_ITEMS):
        items = ItemService().list_items()
        result["low_stock_count"] = sum(
            1
            for it in items
            if (it.get("reorder_level") or 0) > 0
            and it.get("current_stock", 0) <= it["reorder_level"]
        )

    return result
