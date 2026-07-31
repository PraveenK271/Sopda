"""H6 check: verify, then lock.

Asserts:
- with a lock at 31-07-2026, creating a record dated on/before it raises
  (sales, purchase AND banking — the lock is enforced in the services), while a
  record dated after it saves normally
- lock() refuses a second active lock; unlock() requires a reason; after unlock,
  the previously-blocked date saves
- the verify screen's stock figures match ItemService.get_current_stock() for
  every item

Runs on a DISPOSABLE database (sets a period lock + creates invoices — a lock on
the real DB would block live entry). Point GEMINI_DB_URL at a throwaway SQLite.

Run with: python check_h6.py
"""

from datetime import date, datetime

from database import DATABASE_URL
from services.banking_service import BankingService
from services.customer_service import CustomerService
from services.item_service import ItemService
from services.period_lock_service import PeriodLockService
from services.purchase_service import PurchaseService
from services.sales_service import SalesService
from services.supplier_service import SupplierService

LOCK_DATE = date(2026, 7, 31)
BLOCKED = date(2026, 7, 15)
ALLOWED = date(2026, 8, 5)


def _blocked(fn):
    try:
        fn()
        return False
    except ValueError as exc:
        return "locked" in str(exc).lower()


def main():
    if "mssql" in DATABASE_URL:
        raise SystemExit("Refusing to run against SQL Server (sets a period lock). Use a throwaway SQLite DB.")

    stamp = datetime.now().strftime("%H%M%S%f")
    lock = PeriodLockService()
    sales, purchases, banking = SalesService(), PurchaseService(), BankingService()

    item = ItemService().add_item(code=f"H6-A-{stamp}", name="Item", unit="PCS", gst_rate=18, opening_stock=100, created_by="check_h6")
    cust = CustomerService().add_customer(name=f"H6 Cust {stamp}", state="Andhra Pradesh", created_by="check_h6")
    supp = SupplierService().add_supplier(name=f"H6 Supp {stamp}", state="Andhra Pradesh", created_by="check_h6")
    line = [{"item_id": item.id, "quantity": 1, "rate": 100}]

    assert not lock.is_locked(BLOCKED), "should be unlocked before we lock"
    lock.lock(LOCK_DATE, "check_h6", "FY history verified")
    assert lock.is_locked(BLOCKED) and lock.is_locked(LOCK_DATE) and not lock.is_locked(ALLOWED)
    print(f"Locked up to {LOCK_DATE.strftime('%d-%m-%Y')}")

    # Every transactional service refuses a locked date.
    assert _blocked(lambda: sales.create_invoice(f"H6-S-{stamp}", BLOCKED, cust.id, line, "check_h6")), "sales not blocked"
    assert _blocked(lambda: purchases.create_purchase_invoice(f"H6-P-{stamp}", BLOCKED, supp.id, line, "check_h6")), "purchase not blocked"
    assert _blocked(lambda: banking.record_receipt(date=BLOCKED, customer_id=cust.id, amount=100, payment_mode="CASH", created_by="check_h6")), "receipt not blocked"
    print("Sales, purchase and receipt dated 15-07-2026 all refused")

    # A date after the lock saves.
    inv = sales.create_invoice(f"H6-OK-{stamp}", ALLOWED, cust.id, line, "check_h6")
    assert inv.id is not None
    print("Invoice dated 05-08-2026 saved normally")

    # A second active lock is refused; unlock needs a reason.
    try:
        lock.lock(date(2026, 8, 31), "check_h6", "x")
        raise AssertionError("second lock was not refused")
    except ValueError:
        pass
    try:
        lock.unlock("check_h6", "")
        raise AssertionError("unlock without a reason was allowed")
    except ValueError:
        pass
    print("Second lock refused; unlock requires a reason")

    # Unlock, then the previously-blocked date saves.
    lock.unlock("check_h6", "correcting a mis-typed opening figure")
    assert not lock.is_locked(BLOCKED)
    inv2 = sales.create_invoice(f"H6-AFTER-{stamp}", BLOCKED, cust.id, line, "check_h6")
    assert inv2.id is not None
    print("After unlock, the 15-07-2026 invoice saves")

    # Verify screen's stock figures == get_current_stock for every item.
    item_service = ItemService()
    for it in item_service.list_items():
        assert it["current_stock"] == item_service.get_current_stock(it["id"]), f"stock mismatch for {it['code']}"
    print("Verify screen stock figures match get_current_stock for every item")

    print("PASS")


if __name__ == "__main__":
    main()
