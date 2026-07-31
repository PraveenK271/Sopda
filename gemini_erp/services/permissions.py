"""Module permission keys and the per-role permission sets.

These keys are the single source of truth shared by the UI (which tabs to build)
and the auth service (has_permission). Defining them here means the two can
never disagree about a module's name.

Scope note (Milestone 26/27): permissions are TAB-LEVEL only — a role either
sees a screen or it does not. Fine-grained read-only vs edit within a screen is
out of scope (recorded in progress.md).
"""

MODULE_ITEMS = "items"
MODULE_BILLING = "billing"
MODULE_PURCHASES = "purchases"
MODULE_SALES_LOG = "sales_log"
MODULE_PURCHASE_LOG = "purchase_log"
MODULE_ACCOUNTS = "accounts"
MODULE_BANKING = "banking"
MODULE_GST = "gst"
MODULE_DOCUMENTS = "documents"
MODULE_SETTINGS = "settings"
MODULE_USERS = "users"  # user-management screen
MODULE_DATA_IMPORT = "data_import"  # historical bulk-import screen (Administrator only)

ALL_MODULES = [
    MODULE_ITEMS,
    MODULE_BILLING,
    MODULE_PURCHASES,
    MODULE_SALES_LOG,
    MODULE_PURCHASE_LOG,
    MODULE_ACCOUNTS,
    MODULE_BANKING,
    MODULE_GST,
    MODULE_DOCUMENTS,
    MODULE_SETTINGS,
    MODULE_USERS,
    MODULE_DATA_IMPORT,
]

# Role names (kept as constants so the seed and any lookups agree).
ROLE_ADMINISTRATOR = "Administrator"
ROLE_ACCOUNTANT = "Accountant"
ROLE_INVENTORY_MANAGER = "Inventory Manager"
ROLE_SALES_USER = "Sales User"

# Permission set per role (from Instructions_Claude.txt Module 2).
ROLE_PERMISSIONS = {
    ROLE_ADMINISTRATOR: list(ALL_MODULES),
    ROLE_ACCOUNTANT: [
        MODULE_ACCOUNTS,
        MODULE_PURCHASES,
        MODULE_PURCHASE_LOG,
        MODULE_BILLING,
        MODULE_SALES_LOG,
        MODULE_GST,
        MODULE_DOCUMENTS,
    ],
    ROLE_INVENTORY_MANAGER: [
        MODULE_ITEMS,
        MODULE_PURCHASES,
        MODULE_PURCHASE_LOG,
        MODULE_DOCUMENTS,
    ],
    # Sales User sees Items as a read-only view; tab-level only for now.
    ROLE_SALES_USER: [
        MODULE_BILLING,
        MODULE_SALES_LOG,
        MODULE_ITEMS,
    ],
}
