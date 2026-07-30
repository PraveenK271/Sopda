"""Milestone 25 check: company profile drives the invoice PDF, and backups work.

Proves:
1. SettingsService.update_profile() persists and get_profile() reads it back.
2. A generated invoice PDF uses those company-profile values (not hardcoded
   constants) — we set unique markers and find them in the rendered PDF.
3. BackupService.backup() produces a backup artifact on the current backend.

The real company profile is captured up front and restored at the end, so the
check leaves the profile as it found it.

Run with: python check_milestone25.py
"""

import os
import tempfile
from datetime import date, datetime

import reportlab.rl_config

from reports.invoice_pdf import generate_invoice_pdf
from services.backup_service import BackupService
from services.customer_service import CustomerService
from services.item_service import ItemService
from services.sales_service import SalesService
from services.settings_service import SettingsService

# Render PDFs uncompressed so the marker text is greppable in the raw bytes.
# (Nothing else relies on this; it only affects this check's generated file.)
reportlab.rl_config.pageCompression = 0


def _create_sale() -> int:
    """Create a fresh item + customer + invoice; return the invoice id."""
    stamp = datetime.now().strftime("%H%M%S")
    item = ItemService().add_item(
        code=f"CHK-M25-ITEM-{stamp}",
        name="Milestone 25 Check Item",
        unit="PCS",
        gst_rate=18,
        opening_stock=50,
        reorder_level=5,
    )
    customer = CustomerService().add_customer(
        name=f"CHK-M25 Customer {stamp}",
        gstin="37AAAAA0000A1Z5",
        state="Andhra Pradesh",
        address="Test Address",
    )
    invoice = SalesService().create_invoice(
        invoice_no=f"CHK-M25-INV-{stamp}",
        invoice_date=date.today(),
        customer_id=customer.id,
        lines=[{"item_id": item.id, "quantity": 2, "rate": 100}],
    )
    return invoice.id


def main():
    settings = SettingsService()
    original = settings.get_profile()

    stamp = datetime.now().strftime("%H%M%S")
    name_marker = f"CHK-M25-TRADERS-{stamp}"
    gstin_marker = f"37CHKM25{stamp}Z5"  # fits String(20)
    bank_marker = f"CHK-M25-BANK-{stamp}"
    term_marker = f"CHK-M25-TERM-{stamp}"

    pdf_path = os.path.join(tempfile.gettempdir(), f"chk_m25_{stamp}.pdf")

    try:
        # 1. Update the profile with unique markers and read it back.
        settings.update_profile(
            {
                "name": name_marker,
                "gstin": gstin_marker,
                "bank_name": bank_marker,
                "terms": [term_marker, "Second line term."],
            }
        )
        saved = settings.get_profile()
        assert saved["name"] == name_marker, saved["name"]
        assert saved["gstin"] == gstin_marker, saved["gstin"]
        assert saved["bank_name"] == bank_marker, saved["bank_name"]
        assert term_marker in saved["terms"], saved["terms"]
        print(f"Profile updated and read back: name={saved['name']}")

        # 2. Generate an invoice PDF and confirm it used the profile values.
        invoice_id = _create_sale()
        generate_invoice_pdf(invoice_id, pdf_path)
        assert os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0, "PDF not produced"
        pdf_bytes = open(pdf_path, "rb").read()
        text = pdf_bytes.decode("latin-1")
        for marker in (name_marker, gstin_marker, bank_marker, term_marker):
            assert marker in text, f"Marker {marker!r} not found in the PDF"
        print(f"Invoice PDF at {pdf_path} contains all company-profile markers")

        # 3. Backup produces an artifact on the current backend.
        backup_service = BackupService()
        backup_path = backup_service.backup()
        if backup_service.is_sqlite():
            # SQLite backup is a client-side file copy — verify it directly.
            assert os.path.exists(backup_path) and os.path.getsize(backup_path) > 0, "Backup not produced"
            print(f"Backup created: {backup_path} ({os.path.getsize(backup_path)} bytes)")
        else:
            # SQL Server writes server-side to an ACL'd folder the client can't
            # stat; backup() self-verifies with RESTORE VERIFYONLY and raises on
            # failure, so a returned path means a valid backup set exists.
            assert backup_path, "Backup path not returned"
            print(f"Backup created (server-side, VERIFYONLY passed): {backup_path}")

        print("PASS")
    finally:
        # Restore the profile exactly as it was.
        settings.update_profile(original)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


if __name__ == "__main__":
    main()
