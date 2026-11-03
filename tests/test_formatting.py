from decimal import Decimal

from critisizer.formatting import round_score


def test_ties_round_half_up():
    assert round_score(Decimal("41.25")) == Decimal("41.3")
    assert round_score(Decimal("0.05")) == Decimal("0.1")


def test_non_ties_round_normally():
    assert round_score(Decimal("16.8333333")) == Decimal("16.8")
    assert round_score(Decimal("59.0833")) == Decimal("59.1")
    assert round_score(Decimal(70)) == Decimal("70.0")
