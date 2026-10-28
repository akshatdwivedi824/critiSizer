"""Pure scoring functions.

No database, web or clock access belongs in this package.
Rounding rule: nothing is rounded in here. Round once, at the output.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

ALLOWED_MULTIPLIERS = frozenset(
    {Decimal("1.0"), Decimal("0.8"), Decimal("0.5"), Decimal(0)}
)


class ScoringError(ValueError):
    """Raised when scoring input breaks a rule."""


@dataclass(frozen=True)
class IndicatorInput:
    score: Decimal
    weight: Decimal
    multiplier: Decimal


def _validate(item: IndicatorInput) -> None:
    if not Decimal(0) <= item.score <= Decimal(100):
        raise ScoringError(f"score out of range: {item.score}")
    if item.weight <= 0:
        raise ScoringError(f"weight must be positive: {item.weight}")
    if item.multiplier not in ALLOWED_MULTIPLIERS:
        raise ScoringError(f"multiplier not allowed: {item.multiplier}")


def aspect_score(indicators: Sequence[IndicatorInput]) -> Decimal | None:
    """Weighted mean of indicator scores, scaled by verification multipliers.

    Indicators with multiplier 0 (allegations) are excluded from both the
    numerator and the sum of weights. Returns None if nothing is left.
    """
    used = []
    for item in indicators:
        _validate(item)
        if item.multiplier > 0:
            used.append(item)
    if not used:
        return None
    total_weight = sum((i.weight for i in used), Decimal(0))
    weighted = sum((i.weight * i.multiplier * i.score for i in used), Decimal(0))
    return weighted / total_weight