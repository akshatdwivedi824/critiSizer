"""Pure scoring functions.

No database, web or clock access belongs in this package.
Rounding rule: nothing is rounded in here. Round once, at the output.
"""

from collections.abc import Mapping, Sequence
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

VALID_STATUSES = frozenset({"pending", "accepted", "rejected"})


@dataclass(frozen=True)
class Rubric:
    label: str
    weights: Mapping[str, Decimal]
    min_ratings: int = 5
    spike_threshold: Decimal = Decimal(80)
    people_weight: Decimal = Decimal(1)


@dataclass(frozen=True)
class RatingInput:
    value: Decimal
    status: str


@dataclass(frozen=True)
class OverallResult:
    rubric_label: str
    aspect_scores: Mapping[str, Decimal]
    expert_average: Decimal
    people_rating: Decimal | None
    people_rating_count: int
    overall_rating: Decimal
    spike_flag: bool


def _check_inputs(
    aspect_scores: Mapping[str, Decimal | None], rubric: Rubric
) -> None:
    if not rubric.weights:
        raise ScoringError("rubric has no aspects")
    if set(aspect_scores) != set(rubric.weights):
        raise ScoringError("aspect scores must match the rubric's aspects exactly")
    for code, score in aspect_scores.items():
        if score is None:
            raise ScoringError(f"aspect has no valid evidence: {code}")
        if not Decimal(0) <= score <= Decimal(100):
            raise ScoringError(f"aspect score out of range: {code}={score}")
    for code, weight in rubric.weights.items():
        if weight <= 0:
            raise ScoringError(f"aspect weight must be positive: {code}={weight}")
    if rubric.people_weight <= 0:
        raise ScoringError("people's rating weight must be positive")
    if rubric.min_ratings < 1:
        raise ScoringError("min_ratings must be at least 1")


def expert_average(aspect_scores: Mapping[str, Decimal], rubric: Rubric) -> Decimal:
    _check_inputs(aspect_scores, rubric)
    total_weight = sum(rubric.weights.values(), Decimal(0))
    weighted = sum(
        (rubric.weights[code] * score for code, score in aspect_scores.items()),
        Decimal(0),
    )
    return weighted / total_weight


def people_rating(
    ratings: Sequence[RatingInput], min_ratings: int
) -> tuple[Decimal | None, int]:
    """Mean of accepted ratings, or None if there are fewer than min_ratings."""
    if min_ratings < 1:
        raise ScoringError("min_ratings must be at least 1")
    accepted = []
    for rating in ratings:
        if rating.status not in VALID_STATUSES:
            raise ScoringError(f"unknown rating status: {rating.status}")
        if not Decimal(0) <= rating.value <= Decimal(100):
            raise ScoringError(f"rating out of range: {rating.value}")
        if rating.status == "accepted":
            accepted.append(rating.value)
    count = len(accepted)
    if count < min_ratings:
        return None, count
    return sum(accepted, Decimal(0)) / count, count


def overall_rating(
    aspect_scores: Mapping[str, Decimal],
    ratings: Sequence[RatingInput],
    rubric: Rubric,
) -> OverallResult:
    _check_inputs(aspect_scores, rubric)
    people, count = people_rating(ratings, rubric.min_ratings)
    weighted = sum(
        (rubric.weights[code] * score for code, score in aspect_scores.items()),
        Decimal(0),
    )
    total_weight = sum(rubric.weights.values(), Decimal(0))
    if people is not None:
        weighted += rubric.people_weight * people
        total_weight += rubric.people_weight
    return OverallResult(
        rubric_label=rubric.label,
        aspect_scores=dict(aspect_scores),
        expert_average=expert_average(aspect_scores, rubric),
        people_rating=people,
        people_rating_count=count,
        overall_rating=weighted / total_weight,
        spike_flag=max(aspect_scores.values()) >= rubric.spike_threshold,
    )