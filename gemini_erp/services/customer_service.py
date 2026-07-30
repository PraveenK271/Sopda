"""Business logic for the (basic) Customer Master."""

import logging

from sqlalchemy import false, true
from database import get_session
from models import Customer, LedgerAccount

logger = logging.getLogger(__name__)


class CustomerService:
    """Add customers and list them for GST invoicing."""

    def add_customer(
        self,
        name: str,
        gstin: str | None = None,
        address: str | None = None,
        state: str | None = None,
        created_by: str | None = None,
    ) -> Customer:
        session = get_session()
        try:
            customer = Customer(
                name=name,
                gstin=gstin,
                address=address,
                state=state,
                created_by=created_by,
            )
            session.add(customer)
            session.flush()

            ledger_account = LedgerAccount(
                name=name,
                account_type="ASSET",
                account_group="Sundry Debtors",
                customer_id=customer.id,
                created_by=created_by,
            )
            session.add(ledger_account)

            session.commit()
            session.refresh(customer)
            logger.info("Added customer %s with linked ledger account", customer.name)
            return customer
        except Exception:
            session.rollback()
            logger.exception("Failed to add customer %s", name)
            raise
        finally:
            session.close()

    def list_customers(self) -> list[dict]:
        session = get_session()
        try:
            customers = (
                session.query(Customer)
                .filter(Customer.is_deleted == false())
                .order_by(Customer.id)
                .all()
            )
            return [
                {
                    "id": c.id,
                    "name": c.name,
                    "gstin": c.gstin,
                    "address": c.address,
                    "state": c.state,
                }
                for c in customers
            ]
        except Exception:
            logger.exception("Failed to list customers")
            raise
        finally:
            session.close()
