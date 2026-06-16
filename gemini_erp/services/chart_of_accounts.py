"""System ledger account codes and a seed function to ensure they exist.

These codes are looked up by AccountingService.get_account_by_code() when
posting journal entries for sales/purchases (Milestone 11+).
"""

import logging

from models import LedgerAccount

logger = logging.getLogger(__name__)

# System account codes
SALES = "SALES"
PURCHASE = "PURCHASE"
CASH = "CASH"
CGST_OUTPUT = "CGST_OUTPUT"
SGST_OUTPUT = "SGST_OUTPUT"
IGST_OUTPUT = "IGST_OUTPUT"
CGST_INPUT = "CGST_INPUT"
SGST_INPUT = "SGST_INPUT"
IGST_INPUT = "IGST_INPUT"

# (name, account_type, account_group) for each system account code
SYSTEM_ACCOUNTS = {
    SALES: ("Sales Account", "INCOME", "Sales Accounts"),
    PURCHASE: ("Purchase Account", "EXPENSE", "Purchase Accounts"),
    CASH: ("Cash", "ASSET", "Cash-in-hand"),
    CGST_OUTPUT: ("CGST Output", "LIABILITY", "Duties & Taxes"),
    SGST_OUTPUT: ("SGST Output", "LIABILITY", "Duties & Taxes"),
    IGST_OUTPUT: ("IGST Output", "LIABILITY", "Duties & Taxes"),
    CGST_INPUT: ("CGST Input", "ASSET", "Duties & Taxes"),
    SGST_INPUT: ("SGST Input", "ASSET", "Duties & Taxes"),
    IGST_INPUT: ("IGST Input", "ASSET", "Duties & Taxes"),
}


def ensure_system_accounts(session) -> None:
    """Create any missing system ledger accounts. Idempotent.

    Commits on the passed-in session, so it is safe to call on its own
    (e.g. from create_db.py or on app start).
    """
    try:
        existing_codes = {
            code
            for (code,) in session.query(LedgerAccount.code).filter(LedgerAccount.code.isnot(None))
        }
        for code, (name, account_type, account_group) in SYSTEM_ACCOUNTS.items():
            if code in existing_codes:
                continue
            session.add(
                LedgerAccount(
                    name=name,
                    code=code,
                    account_type=account_type,
                    account_group=account_group,
                )
            )
            logger.info("Created system ledger account %s", code)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Failed to ensure system accounts")
        raise
