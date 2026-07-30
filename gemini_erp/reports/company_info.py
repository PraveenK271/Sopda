"""Default seller (our company) details — seed values only (Phase 4+).

These are no longer read at print time. The live company profile lives in the
``company_profile`` database table and is edited on the Settings screen
(``SettingsService``); invoices/reports read it from there. On the very first
run these constants seed that single row, so a fresh install still prints
something sensible. Edit the real values in Settings, not here.
"""

COMPANY_NAME = "Your Company Name"
COMPANY_ADDRESS = "Address line 1, Town, Andhra Pradesh - 500000"
COMPANY_MOBILE = "+91-0000000000"
COMPANY_GSTIN = "37AAAAA0000A1Z5"
COMPANY_STATE = "Andhra Pradesh"

# Bank details printed on the invoice for payment.
BANK_NAME = "Your Bank Name"
BANK_ACCOUNT_NO = "XXXXXXXXXXXX"
BANK_IFSC = "XXXX0000000"
BANK_BRANCH = "Branch Name"

# Printed as a numbered list under "Terms & Conditions".
TERMS_AND_CONDITIONS = [
    "Goods once sold will not be taken back or exchanged.",
    "All disputes are subject to local jurisdiction only.",
]
