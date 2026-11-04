from decimal import Decimal

from critisizer.scoring.engine import RatingInput, Rubric, overall_rating

CODES = ["a1", "a2", "a3", "a4", "a5", "a6"]
rubric = Rubric(label="v1", weights={code: Decimal(1) for code in CODES})


def scores(values):
    return dict(zip(CODES, map(Decimal, values), strict=True))


def accepted(values):
    return [RatingInput(Decimal(v), "accepted") for v in values]


a = overall_rating(
    scores([72, 55, 80, 64, 40, 58]), accepted([70, 65, 80, 75, 60]), rubric
)
b = overall_rating(scores([35, 28, 20, 42, 15, 30]), accepted([30, 45, 25]), rubric)
print("A", a.overall_rating.quantize(Decimal("0.1")), a.spike_flag)
print("B", b.overall_rating.quantize(Decimal("0.1")), b.spike_flag)
