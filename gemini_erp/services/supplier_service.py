"""Business logic for the (basic) Supplier Master."""

import logging

from database import get_session
from models import LedgerAccount, Supplier

logger = logging.getLogger(__name__)


class SupplierService:
    """Add suppliers and list them for purchase entry."""

    def add_supplier(
        self,
        name: str,
        gstin: str | None = None,
        address: str | None = None,
        state: str | None = None,
        created_by: str | None = None,
    ) -> Supplier:
        session = get_session()
        try:
            supplier = Supplier(
                name=name,
                gstin=gstin,
                address=address,
                state=state,
                created_by=created_by,
            )
            session.add(supplier)
            session.flush()

            ledger_account = LedgerAccount(
                name=name,
                account_type="LIABILITY",
                account_group="Sundry Creditors",
                supplier_id=supplier.id,
                created_by=created_by,
            )
            session.add(ledger_account)

            session.commit()
            session.refresh(supplier)
            logger.info("Added supplier %s with linked ledger account", supplier.name)
            return supplier
        except Exception:
            session.rollback()
            logger.exception("Failed to add supplier %s", name)
            raise
        finally:
            session.close()

    def list_suppliers(self) -> list[dict]:
        session = get_session()
        try:
            suppliers = (
                session.query(Supplier)
                .filter(Supplier.is_deleted.is_(False))
                .order_by(Supplier.id)
                .all()
            )
            return [
                {
                    "id": s.id,
                    "name": s.name,
                    "gstin": s.gstin,
                    "address": s.address,
                    "state": s.state,
                }
                for s in suppliers
            ]
        except Exception:
            logger.exception("Failed to list suppliers")
            raise
        finally:
            session.close()
