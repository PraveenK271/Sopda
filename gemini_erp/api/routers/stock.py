"""Stock levels + reorder alerts (module: items)."""

from fastapi import APIRouter, Depends

from api.auth import require_permission
from services.item_service import ItemService
from services.permissions import MODULE_ITEMS

router = APIRouter(prefix="/api/stock", tags=["stock"])


def _annotate(items: list[dict]) -> list[dict]:
    """Add a low_stock flag: at/below the reorder level (only if one is set)."""
    for item in items:
        reorder = item.get("reorder_level") or 0
        item["low_stock"] = reorder > 0 and item.get("current_stock", 0) <= reorder
    return items


@router.get("", dependencies=[Depends(require_permission(MODULE_ITEMS))])
def stock():
    return _annotate(ItemService().list_items())


@router.get("/reorder", dependencies=[Depends(require_permission(MODULE_ITEMS))])
def reorder_alerts():
    """Only the items at or below their reorder level."""
    return [item for item in _annotate(ItemService().list_items()) if item["low_stock"]]
