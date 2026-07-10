"""OCR service check (Milestone 21).

Tests the paddle-free parts of OCRService WITHOUT needing real bill images or
the engine (so it runs on the main Python 3.14 interpreter):

  1. _parse_results() on a typical Indian bill -> GSTIN, invoice no, total
  2. raw_text with no GSTIN -> supplier_gstin is None + a warning
  3. malformed amounts ("1,234.56" and "₹ 1234") -> both parse to float
  4. extract_from_file() on a missing path -> standard dict, confidence 0.0,
     a warning, and NO exception

The real end-to-end OCR (engine + model download + real bills) is a manual
step — see CHECKLIST_PHASE3.md Milestone 21.
"""

from services.ocr_service import OCRService, confidence_band

TYPICAL_BILL = """ABC Traders Pvt Ltd
123 Market Road, Vijayawada, Andhra Pradesh
GSTIN: 37ABCDE1234F1Z5
Invoice No: INV-2024-001
Date: 15/04/2024
Item        HSN     Qty   Rate    Amount
Steel Rod   7214    10    100.00  1000.00
Taxable Value 1000.00
CGST 9% 90.00
SGST 9% 90.00
Grand Total 1180.00
"""

NO_GSTIN_BILL = """Local Hardware Store
Invoice No: LH-77
Date: 01-05-2024
Total 500.00
"""

MALFORMED_AMOUNTS = """Some Supplier
Total 1,234.56
CGST ₹ 1234
"""


def check_typical_bill(service):
    parsed = service._parse_results(TYPICAL_BILL)
    assert parsed["supplier_gstin"] == "37ABCDE1234F1Z5", parsed["supplier_gstin"]
    assert parsed["invoice_number"] == "INV-2024-001", parsed["invoice_number"]
    assert parsed["invoice_date"] == "15/04/2024", parsed["invoice_date"]
    assert parsed["taxable_amount"] == 1000.00, parsed["taxable_amount"]
    assert parsed["cgst"] == 90.00, parsed["cgst"]
    assert parsed["sgst"] == 90.00, parsed["sgst"]
    assert parsed["total_amount"] == 1180.00, parsed["total_amount"]
    print("[1] typical bill: GSTIN/invoice/date/amounts extracted OK")


def check_no_gstin(service):
    parsed = service._parse_results(NO_GSTIN_BILL)
    assert parsed["supplier_gstin"] is None, parsed["supplier_gstin"]
    assert any("GSTIN" in w for w in parsed["warnings"]), parsed["warnings"]
    print("[2] no GSTIN: supplier_gstin is None + warning present OK")


def check_malformed_amounts(service):
    parsed = service._parse_results(MALFORMED_AMOUNTS)
    assert parsed["total_amount"] == 1234.56, parsed["total_amount"]
    assert parsed["cgst"] == 1234.00, parsed["cgst"]
    print("[3] malformed amounts: '1,234.56' and 'Rs 1234' parsed OK")


def check_missing_file(service):
    result = service.extract_from_file("this_file_does_not_exist_xyz.png")
    assert result["confidence"] == 0.0, result["confidence"]
    assert result["raw_text"] == "", repr(result["raw_text"])
    assert any("not found" in w.lower() for w in result["warnings"]), result["warnings"]
    # standard dict shape is intact
    for key in ("supplier_name", "line_items", "total_amount", "warnings"):
        assert key in result, key
    print("[4] missing file: standard dict, confidence 0.0, warning, no crash OK")


def check_confidence_band():
    assert confidence_band(0.90) == "High confidence"
    assert confidence_band(0.70).startswith("Medium")
    assert confidence_band(0.40).startswith("Low")
    print("[5] confidence bands: High/Medium/Low thresholds OK")


def main():
    service = OCRService()
    check_typical_bill(service)
    check_no_gstin(service)
    check_malformed_amounts(service)
    check_missing_file(service)
    check_confidence_band()
    print("\nAll OCR service checks passed.")


if __name__ == "__main__":
    main()
