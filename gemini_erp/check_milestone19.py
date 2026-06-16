"""Milestone 19 check: GSTR-1 and GSTR-3B summaries.

Reuses the Milestone 18 fixtures (build_fixtures()) on the same sentinel date
range, so the figures are isolated from real dev-DB invoices.

Expected, from the M18 fixtures:
  Sales: GST cust 1000/90/90/0, NoGST cust 200/5/5/0, KA cust 500/0/0/90
  Purchase: 1000/90/90/0

  GSTR-1
    b2b       : 2 invoices (GST customer + KA customer)
    b2c_small : taxable 200, cgst 5, sgst 5, igst 0   (the no-GSTIN customer)
  GSTR-3B
    outward : taxable 1700, cgst 95, sgst 95, igst 90
    itc     : cgst 90, sgst 90, igst 0
    net payable : cgst 5, sgst 5, igst 90 ; nothing carried forward

Run with: ../venv/Scripts/python.exe check_milestone19.py
"""

from check_milestone18 import (
    SALE_GST_NO,
    SALE_KA_NO,
    build_fixtures,
)
from services.gst_report_service import GstReportService


def main():
    date_from, date_to = build_fixtures()

    # --- GSTR-1 ---
    g1 = GstReportService.get_gstr1_summary(date_from, date_to)

    b2b_by_no = {r["invoice_no"]: r for r in g1["b2b"]}
    assert set(b2b_by_no) == {SALE_GST_NO, SALE_KA_NO}, f"Unexpected B2B set: {set(b2b_by_no)}"

    gst_inv = b2b_by_no[SALE_GST_NO]
    assert (gst_inv["taxable_value"], gst_inv["cgst"], gst_inv["sgst"], gst_inv["igst"]) == \
        (1000.0, 90.0, 90.0, 0.0), gst_inv
    assert gst_inv["gstin"] == "37AAAAA0000A1Z5", gst_inv

    ka_inv = b2b_by_no[SALE_KA_NO]
    assert (ka_inv["taxable_value"], ka_inv["cgst"], ka_inv["sgst"], ka_inv["igst"]) == \
        (500.0, 0.0, 0.0, 90.0), ka_inv

    b2c = g1["b2c_small"]
    assert (b2c["taxable_value"], b2c["cgst"], b2c["sgst"], b2c["igst"]) == (200.0, 5.0, 5.0, 0.0), b2c

    assert len(g1["hsn_summary"]) == 2, g1["hsn_summary"]
    print("GSTR-1: 2 B2B invoices, B2C small 200/5/5/0, HSN 2 groups OK")

    # --- GSTR-3B ---
    g3 = GstReportService.get_gstr3b_summary(date_from, date_to)

    outward = g3["outward_taxable_supplies"]
    assert (outward["taxable_amount"], outward["cgst"], outward["sgst"], outward["igst"]) == \
        (1700.0, 95.0, 95.0, 90.0), outward

    itc = g3["itc_available"]
    assert (itc["cgst"], itc["sgst"], itc["igst"]) == (90.0, 90.0, 0.0), itc

    # Manually computed net payable per head: output - ITC, floored at 0.
    net = g3["net_tax_payable"]
    assert net["cgst"] == round(95.0 - 90.0, 2) == 5.0, net
    assert net["sgst"] == round(95.0 - 90.0, 2) == 5.0, net
    assert net["igst"] == round(90.0 - 0.0, 2) == 90.0, net

    cf = g3["itc_carried_forward"]
    assert cf == {"cgst": 0.0, "sgst": 0.0, "igst": 0.0}, cf
    print("GSTR-3B: outward 1700/95/95/90, ITC 90/90/0, net payable 5/5/90 OK")

    print("PASS")


if __name__ == "__main__":
    main()
