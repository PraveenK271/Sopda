"""Convert a rupee amount into words using the Indian numbering system
(thousand / lakh / crore), e.g. 49475.04 -> "Forty Nine Thousand Four
Hundred and Seventy Five Rupees Only".
"""

from decimal import Decimal

_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
]
_TENS = [
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety",
]


def _two_digit_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (" " + _ONES[ones] if ones else "")


def _three_digit_words(n: int) -> str:
    if n < 100:
        return _two_digit_words(n)
    hundreds, rest = divmod(n, 100)
    words = _ONES[hundreds] + " Hundred"
    if rest:
        words += " and " + _two_digit_words(rest)
    return words


def amount_to_words(amount: Decimal | float | int) -> str:
    """Whole-rupee part of amount, spelled out, e.g. "Forty Nine Thousand ... Rupees Only"."""
    rupees = int(Decimal(str(amount)))

    if rupees == 0:
        return "Zero Rupees Only"

    crore, rupees = divmod(rupees, 1_00_00_000)
    lakh, rupees = divmod(rupees, 1_00_000)
    thousand, hundred = divmod(rupees, 1_000)

    parts = []
    if crore:
        parts.append(_three_digit_words(crore) + " Crore")
    if lakh:
        parts.append(_three_digit_words(lakh) + " Lakh")
    if thousand:
        parts.append(_three_digit_words(thousand) + " Thousand")
    if hundred:
        parts.append(_three_digit_words(hundred))

    return " ".join(parts) + " Rupees Only"
