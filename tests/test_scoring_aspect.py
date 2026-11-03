from decimal import Decimal

import pytest

from critisizer.scoring.engine import IndicatorInput, ScoringError, aspect_score


def ind(score, weight="1", multiplier="1.0"):
    return IndicatorInput(Decimal(score), Decimal(weight), Decimal(multiplier))


def test_hand_example():
    # (75 * 1.0 + 50 * 0.8 + 25 * 0.5) / 3 = (75 + 40 + 12.5) / 3 = 42.5
    result = aspect_score(
        [
            ind("75", multiplier="1.0"),
            ind("50", multiplier="0.8"),
            ind("25", multiplier="0.5"),
        ]
    )
    assert result == Decimal("42.5")


def test_weights_change_the_result():
    # (50 * 1 + 100 * 3) / 4 = 87.5
    assert aspect_score([ind("50", "1"), ind("100", "3")]) == Decimal("87.5")


def test_excluded_indicator_is_ignored():
    result = aspect_score([ind("75"), ind("90", multiplier="0")])
    assert result == Decimal(75)


def test_all_excluded_gives_none():
    assert aspect_score([ind("90", multiplier="0")]) is None


def test_empty_list_gives_none():
    assert aspect_score([]) is None


@pytest.mark.parametrize(
    "bad",
    [
        ind("101"),
        ind("-1"),
        ind("50", weight="0"),
        ind("50", weight="-2"),
        ind("50", multiplier="0.7"),
    ],
)
def test_bad_input_raises(bad):
    with pytest.raises(ScoringError):
        aspect_score([bad])
