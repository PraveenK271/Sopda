"""Milestone 4 check: generate a Tax Invoice PDF for a saved invoice.

Depends on the invoices created by check_milestone3.py (CHK-M3-001 / CHK-M3-002).
Run with: python check_milestone3.py  (first time only)
          python check_milestone4.py

Writes PDFs to gemini_erp/output/ (gitignored) and sanity-checks each file.
"""

import os

from database import get_session
from models import SalesInvoice
from reports.invoice_pdf import generate_invoice_pdf

INVOICE_NOS = ["CHK-M3-001", "CHK-M3-002"]
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    session = get_session()
    invoices = {
        inv.invoice_no: inv.id
        for inv in session.query(SalesInvoice)
        .filter(SalesInvoice.invoice_no.in_(INVOICE_NOS))
        .all()
    }
    session.close()

    for invoice_no in INVOICE_NOS:
        invoice_id = invoices.get(invoice_no)
        if invoice_id is None:
            raise SystemExit(f"Run check_milestone3.py first to create invoice {invoice_no}")

        output_path = os.path.join(OUTPUT_DIR, f"{invoice_no}.pdf")
        generate_invoice_pdf(invoice_id, output_path)

        assert os.path.exists(output_path), f"PDF not created: {output_path}"
        with open(output_path, "rb") as f:
            header = f.read(5)
        assert header == b"%PDF-", f"Not a valid PDF: {output_path}"

        size = os.path.getsize(output_path)
        assert size > 1000, f"PDF looks too small ({size} bytes): {output_path}"
        print(f"Generated {output_path} ({size} bytes)")

    print("PASS")


if __name__ == "__main__":
    main()
