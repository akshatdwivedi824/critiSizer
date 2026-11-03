from decimal import Decimal

import pytest
from factories import CODES, add_indicator, fill_policy, make_aspects

from critisizer.models import Evidence
from critisizer.scorecard import indicator_multiplier, load_active_rubric, score_policy
from critisizer.scoring.engine import ScoringError


@pytest.fixture
def aspects(session):
    return make_aspects(session)


def test_score_policy_matches_hand_calculation(session, aspects):
    # Same numbers as the fictional broadband policy: 101 / 6 = 16.83
    policy = fill_policy(
        session,
        aspects,
        "hand-calc",
        {
            "outcome_failure": (20, [1.0]),
            "cost_waste": (15, [1.0]),
            "transparency_gap": (25, [1.0]),
            "ground_level_harm": (20, [0.8]),
            "legal_challenges": (10, [1.0]),
            "equity_impact": (30, [0.5]),
        },
    )
    result = score_policy(session, policy.id, load_active_rubric(session))
    assert abs(result.overall_rating - Decimal(101) / 6) < Decimal("0.0001")
    assert result.spike_flag is False
    assert result.people_rating is None
    assert result.rubric_label == "test-v1"


def test_indicator_weights_are_applied(session, aspects):
    policy = fill_policy(
        session,
        aspects,
        "weights",
        {code: (50, [1.0]) for code in CODES if code != "outcome_failure"},
    )
    add_indicator(session, policy, aspects["outcome_failure"], 75, [1.0], weight=2)
    add_indicator(session, policy, aspects["outcome_failure"], 60, [1.0], weight=1)
    result = score_policy(session, policy.id, load_active_rubric(session))
    # (75*2 + 60*1) / 3 = 70
    assert result.aspect_scores["outcome_failure"] == Decimal(70)


def test_best_evidence_sets_the_indicator_multiplier():
    def ev(value):
        return Evidence(verification_multiplier=Decimal(str(value)))

    assert indicator_multiplier([ev(0), ev(0.8), ev(0.5)]) == Decimal("0.8")
    assert indicator_multiplier([ev(0)]) == Decimal(0)
    assert indicator_multiplier([]) == Decimal(0)


def test_aspect_with_only_an_allegation_is_rejected(session, aspects):
    rows = {code: (40, [1.0]) for code in CODES}
    rows["ground_level_harm"] = (60, [0])
    policy = fill_policy(session, aspects, "all-excluded", rows)
    with pytest.raises(ScoringError, match="no valid evidence"):
        score_policy(session, policy.id, load_active_rubric(session))


def test_spike_flag_is_set_by_one_high_aspect(session, aspects):
    rows = {code: (20, [1.0]) for code in CODES}
    rows["cost_waste"] = (85, [1.0])
    policy = fill_policy(session, aspects, "spike", rows)
    result = score_policy(session, policy.id, load_active_rubric(session))
    assert result.spike_flag is True
