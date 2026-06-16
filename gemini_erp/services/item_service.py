"""Business logic for the Item Master."""

import logging

from sqlalchemy import func
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
                .filter(Item.code == code, Item.is_deleted.is_(False))
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

    def list_items(self) -> list[dict]:
        session = get_session()
        try:
            items = (
                session.query(Item)
                .filter(Item.is_deleted.is_(False))
                .order_by(Item.id)
                .all()
            )
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
        in_qty, out_qty = (
            session.query(
                func.coalesce(
                    func.sum(StockTransaction.quantity).filter(StockTransaction.type == "IN"), 0
                ),
                func.coalesce(
                    func.sum(StockTransaction.quantity).filter(StockTransaction.type == "OUT"), 0
                ),
            )
            .filter(
                StockTransaction.item_id == item.id,
                StockTransaction.is_deleted.is_(False),
            )
            .one()
        )
        return float(item.opening_stock) + float(in_qty) - float(out_qty)
