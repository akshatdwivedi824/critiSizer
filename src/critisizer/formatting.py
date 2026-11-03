from decimal import ROUND_HALF_UP, Decimal

_ONE_DECIMAL = Decimal("0.1")


def round_score(value: Decimal) -> Decimal:
    """Round to one decimal, halves up. Used only at the output, never inside the engine."""
    return value.quantize(_ONE_DECIMAL, rounding=ROUND_HALF_UP)