from decimal import Decimal

import pytest

from critisizer.scorecard import Progress
from critisizer.scoring.engine import (
    RatingInput,
    Rubric,
    ScoringError,
    expert_average,
    overall_rating,
)

CODES = ["a", "b", "c", "d", "e", "f"]


def rubric() -> Rubric:
    return Rubric(label="t", weights={c: Decimal(1) for c in CODES}, min_ratings=5)


def scores(**kw) -> dict[str, Decimal]:
    return {k: Decimal(v) for k, v in kw.items()}


def test_exact_match_still_required_by_default():
    with pytest.raises(ScoringError):
        expert_average(scores(a=50, b=50), rubric())


def test_partial_averages_only_the_given_aspects():
    value = expert_average(scores(a=80, b=40, c=60, d=20), rubric(), partial=True)
    assert value == Decimal(50)


def test_partial_weights_apply_only_to_included_aspects():
    heavy = Rubric(
        label="t",
        weights={**{c: Decimal(1) for c in CODES}, "a": Decimal(3)},
    )
    value = expert_average(scores(a=100, b=0), heavy, partial=True)
    assert value == Decimal(75)  # (3*100 + 1*0) / 4


def test_partial_rejects_unknown_aspect_and_empty_input():
    with pytest.raises(ScoringError):
        expert_average(scores(zzz=10), rubric(), partial=True)
    with pytest.raises(ScoringError):
        expert_average({}, rubric(), partial=True)


def test_overall_partial_spike_uses_included_aspects():
    result = overall_rating(
        scores(a=90, b=10, c=10, d=10),
        [RatingInput(Decimal(50), "pending")],
        rubric(),
        partial=True,
    )
    assert result.spike_flag is True
    assert result.overall_rating == Decimal(30)


def test_projected_and_too_early_do_not_count_toward_rating():
    progress = Progress(
        scored=frozenset({"a", "b", "c"}),
        reviewed=frozenset(),
        total=6,
        projected=frozenset({"d", "e"}),
        too_early=frozenset({"f"}),
    )
    assert progress.assessed == 3
    assert progress.resolved == 6
    assert progress.rated is False


def test_four_assessed_aspects_make_a_rating():
    progress = Progress(
        scored=frozenset({"a", "b", "c"}), reviewed=frozenset({"d"}), total=6
    )
    assert progress.assessed == 4
    assert progress.rated is True


def test_status_precedence():
    progress = Progress(
        scored=frozenset({"a"}),
        reviewed=frozenset({"b"}),
        total=6,
        projected=frozenset({"c"}),
        too_early=frozenset({"d"}),
    )
    assert [progress.status(c) for c in CODES] == [
        "scored",
        "no_negative_evidence",
        "projected",
        "too_early",
        "unresolved",
        "unresolved",
    ]


def test_small_rubrics_can_still_be_rated():
    progress = Progress(scored=frozenset({"a", "b"}), reviewed=frozenset(), total=2)
    assert progress.rated is True