"""GST split logic (see CLAUDE.md).

The business is in Andhra Pradesh:
- Same state as the customer -> split the rate into CGST + SGST (half each)
- Different state -> the full rate goes to IGST
"""

from decimal import ROUND_HALF_UP, Decimal

OUR_STATE = "Andhra Pradesh"


def split_gst(
    taxable_amount: Decimal, gst_rate, customer_state: str | None, our_state: str = OUR_STATE
) -> tuple[Decimal, Decimal, Decimal]:
    """Return (cgst, sgst, igst) for the given taxable amount and GST rate."""
    rate = Decimal(str(gst_rate))
    gst_amount = (taxable_amount * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if customer_state == our_state:
        half = (gst_amount / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return half, half, Decimal("0.00")

    return Decimal("0.00"), Decimal("0.00"), gst_amount
