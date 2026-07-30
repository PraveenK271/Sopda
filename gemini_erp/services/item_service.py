"""Business logic for the Item Master."""

import logging

from sqlalchemy import case, false, func, true
from sqlalchemy.orm import Session

from database import get_session
from models import Item, StockTransaction

logger = logging.getLogger(__name__)


class ItemService:
    """Add items and report on items, including calculated stock."""

    def add_item(
        self,
        code: str,
        name: str,
        hsn_code: str | None = None,
        gst_rate: float = 0,
        unit: str | None = None,
        opening_stock: float = 0,
        reorder_level: float = 0,
        created_by: str | None = None,
    ) -> Item:
        session = get_session()
        try:
            existing = (
                session.query(Item)
                .filter(Item.code == code, Item.is_deleted == false())
                .first()
            )
            if existing is not None:
                raise ValueError(f"Item code '{code}' already exists")

            item = Item(
                code=code,
                name=name,
                hsn_code=hsn_code,
                gst_rate=gst_rate,
                unit=unit,
                opening_stock=opening_stock,
                reorder_level=reorder_level,
                created_by=created_by,
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            logger.info("Added item %s (%s)", item.code, item.name)
            return item
        except Exception:
            session.rollback()
            logger.exception("Failed to add item %s", code)
            raise
        finally:
            session.close()

    def update_item(
        self,
        item_id: int,
        code: str,
        name: str,
        hsn_code: str | None = None,
        gst_rate: float = 0,
        unit: str | None = None,
        opening_stock: float = 0,
        reorder_level: float = 0,
        modified_by: str | None = None,
    ) -> Item:
        """Edit an existing item's master fields.

        Stock is still derived from stock_transactions (opening_stock + IN - OUT),
        so editing opening_stock here changes the current-stock baseline but never
        touches the movement log — the stock rule (CLAUDE.md) is preserved. The
        item code must stay unique among non-deleted items, excluding this one.
        """
        session = get_session()
        try:
            item = session.get(Item, item_id)
            if item is None or item.is_deleted:
                raise ValueError(f"Item {item_id} not found")

            clash = (
                session.query(Item)
                .filter(
                    Item.code == code,
                    Item.id != item_id,
                    Item.is_deleted == false(),
                )
                .first()
            )
            if clash is not None:
                raise ValueError(f"Item code '{code}' already exists")

            item.code = code
            item.name = name
            item.hsn_code = hsn_code
            item.gst_rate = gst_rate
            item.unit = unit
            item.opening_stock = opening_stock
            item.reorder_level = reorder_level
            item.modified_by = modified_by

            session.commit()
            session.refresh(item)
            logger.info("Updated item %s (%s)", item.code, item.name)
            return item
        except Exception:
            session.rollback()
            logger.exception("Failed to update item %s", item_id)
            raise
        finally:
            session.close()

    def list_items(self) -> list[dict]:
        session = get_session()
        try:
            items = (
                session.query(Item)
                .filter(Item.is_deleted == false())
                .order_by(Item.id)
                .all()
            )
            # Net movement (IN - OUT) per item in ONE grouped query, so the whole
            # list costs two queries instead of one get_current_stock per row.
            # Stock is still derived from stock_transactions (never stored), same
            # formula as _calculate_current_stock — the stock rule is preserved.
            movement_rows = (
                session.query(
                    StockTransaction.item_id,
                    func.coalesce(
                        func.sum(
                            case(
                                (StockTransaction.type == "IN", StockTransaction.quantity),
                                (StockTransaction.type == "OUT", -StockTransaction.quantity),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .filter(StockTransaction.is_deleted == false())
                .group_by(StockTransaction.item_id)
                .all()
            )
            net_movement = {item_id: float(net) for item_id, net in movement_rows}
            return [
                {
                    "id": item.id,
                    "code": item.code,
                    "name": item.name,
                    "hsn_code": item.hsn_code,
                    "gst_rate": float(item.gst_rate),
                    "unit": item.unit,
                    "opening_stock": float(item.opening_stock),
                    "reorder_level": float(item.reorder_level),
                    "current_stock": float(item.opening_stock) + net_movement.get(item.id, 0.0),
                }
                for item in items
            ]
        except Exception:
            logger.exception("Failed to list items")
            raise
        finally:
            session.close()

    def get_current_stock(self, item_id: int) -> float:
        session = get_session()
        try:
            item = session.get(Item, item_id)
            if item is None:
                raise ValueError(f"Item {item_id} not found")
            return self._calculate_current_stock(session, item)
        except Exception:
            logger.exception("Failed to calculate current stock for item %s", item_id)
            raise
        finally:
            session.close()

    @staticmethod
    def _calculate_current_stock(session: Session, item: Item) -> float:
        """current_stock = opening_stock + sum(IN) - sum(OUT) from stock_transactions."""
        # SUM(CASE WHEN ...) rather than the SQL aggregate FILTER clause: SQLite
        # supports FILTER but SQL Server does not, so CASE keeps this stock query
        # backend-neutral (same result on both).
        in_qty, out_qty = (
            session.query(
                func.coalesce(
                    func.sum(
                        case((StockTransaction.type == "IN", StockTransaction.quantity), else_=0)
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case((StockTransaction.type == "OUT", StockTransaction.quantity), else_=0)
                    ),
                    0,
                ),
            )
            .filter(
                StockTransaction.item_id == item.id,
                StockTransaction.is_deleted == false(),
            )
            .one()
        )
        return float(item.opening_stock) + float(in_qty) - float(out_qty)
