import random
from decimal import Decimal

import pytest

from critisizer.scoring.engine import (
    RatingInput,
    Rubric,
    ScoringError,
    overall_rating,
    people_rating,
)

CODES = ["a1", "a2", "a3", "a4", "a5", "a6"]
RUBRIC = Rubric(label="v1", weights={code: Decimal(1) for code in CODES})


def scores(values):
    return dict(zip(CODES, [Decimal(str(v)) for v in values], strict=True))


def ratings(values, status="accepted"):
    return [RatingInput(Decimal(str(v)), status) for v in values]


def one_decimal(value):
    return value.quantize(Decimal("0.1"))


def test_policy_a_matches_hand_calculation():
    # (72 + 55 + 80 + 64 + 40 + 58 + 70) / 7 = 439 / 7 = 62.714... -> 62.7
    result = overall_rating(
        scores([72, 55, 80, 64, 40, 58]), ratings([70, 65, 80, 75, 60]), RUBRIC
    )
    assert one_decimal(result.overall_rating) == Decimal("62.7")
    assert result.people_rating == Decimal(70)
    assert result.people_rating_count == 5
    assert result.spike_flag is True


def test_policy_b_ignores_too_few_ratings():
    # (35 + 28 + 20 + 42 + 15 + 30) / 6 = 170 / 6 = 28.333... -> 28.3
    result = overall_rating(
        scores([35, 28, 20, 42, 15, 30]), ratings([30, 45, 25]), RUBRIC
    )
    assert one_decimal(result.overall_rating) == Decimal("28.3")
    assert result.people_rating is None
    assert result.people_rating_count == 3
    assert result.spike_flag is False


def test_five_ratings_are_used_and_four_are_ignored():
    # five: (6 * 50 + 100) / 7 = 400 / 7 = 57.142... -> 57.1; four: 300 / 6 = 50
    flat = scores([50] * 6)
    with_five = overall_rating(flat, ratings([100] * 5), RUBRIC)
    with_four = overall_rating(flat, ratings([100] * 4), RUBRIC)
    assert one_decimal(with_five.overall_rating) == Decimal("57.1")
    assert with_four.overall_rating == Decimal(50)


def test_spike_flag_threshold():
    below = overall_rating(scores([79.9, 10, 10, 10, 10, 10]), [], RUBRIC)
    at = overall_rating(scores([80, 10, 10, 10, 10, 10]), [], RUBRIC)
    assert below.spike_flag is False
    assert at.spike_flag is True


def test_aspect_without_evidence_fails_clearly():
    bad = scores([50] * 6)
    bad["a3"] = None
    with pytest.raises(ScoringError, match="no valid evidence"):
        overall_rating(bad, [], RUBRIC)


def test_pending_and_rejected_ratings_never_count():
    mixed = ratings([70] * 5) + ratings([0], "pending") + ratings([100], "rejected")
    value, count = people_rating(mixed, 5)
    assert value == Decimal(70)
    assert count == 5
    too_few = ratings([70] * 4) + ratings([70] * 3, "pending")
    assert people_rating(too_few, 5) == (None, 4)


def test_new_rubric_version_changes_result_and_old_one_is_unchanged():
    # v1: 100 / 6 = 16.666... -> 16.7; v2 (a1 weight 3): 300 / 8 = 37.5
    v2 = Rubric(
        label="v2",
        weights={**{code: Decimal(1) for code in CODES}, "a1": Decimal(3)},
    )
    only_a1 = scores([100, 0, 0, 0, 0, 0])
    first = overall_rating(only_a1, [], RUBRIC)
    second = overall_rating(only_a1, [], v2)
    assert one_decimal(first.overall_rating) == Decimal("16.7")
    assert second.overall_rating == Decimal("37.5")
    assert first.rubric_label == "v1"
    assert second.rubric_label == "v2"
    assert overall_rating(only_a1, [], RUBRIC) == first


def test_same_input_gives_identical_output_100_times():
    args = (scores([72, 55, 80, 64, 40, 58]), ratings([70, 65, 80, 75, 60]), RUBRIC)
    first = overall_rating(*args)
    assert all(overall_rating(*args) == first for _ in range(100))


def test_results_stay_between_0_and_100_for_random_valid_input():
    rng = random.Random(42)
    for _ in range(200):
        aspect_values = [rng.randint(0, 100) for _ in CODES]
        rating_values = [rng.randint(0, 100) for _ in range(rng.randint(0, 10))]
        result = overall_rating(scores(aspect_values), ratings(rating_values), RUBRIC)
        assert Decimal(0) <= result.overall_rating <= Decimal(100)
        assert Decimal(0) <= result.expert_average <= Decimal(100)


@pytest.mark.parametrize(
    "bad_scores, bad_ratings, rubric",
    [
        (scores([101, 0, 0, 0, 0, 0]), [], RUBRIC),
        (scores([50] * 5 + [-1]), [], RUBRIC),
        ({"a1": Decimal(50)}, [], RUBRIC),
        (scores([50] * 6), ratings([101]), RUBRIC),
        (scores([50] * 6), [RatingInput(Decimal(50), "approved")], RUBRIC),
        (scores([50] * 6), [], Rubric(label="x", weights={}, min_ratings=5)),
        (scores([50] * 6), [], Rubric(label="x", weights=RUBRIC.weights, min_ratings=0)),
    ],
)
def test_bad_input_raises(bad_scores, bad_ratings, rubric):
    with pytest.raises(ScoringError):
        overall_rating(bad_scores, bad_ratings, rubric)


def test_non_positive_aspect_weight_raises():
    rubric = Rubric(label="x", weights={**RUBRIC.weights, "a1": Decimal(0)})
    with pytest.raises(ScoringError, match="weight must be positive"):
        overall_rating(scores([50] * 6), [], rubric)


def test_non_positive_people_weight_raises():
    rubric = Rubric(label="x", weights=RUBRIC.weights, people_weight=Decimal(0))
    with pytest.raises(ScoringError, match="people's rating weight"):
        overall_rating(scores([50] * 6), [], rubric)


def test_people_rating_rejects_min_ratings_below_one():
    with pytest.raises(ScoringError, match="min_ratings"):
        people_rating([], 0)