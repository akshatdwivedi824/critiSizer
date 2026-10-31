from decimal import Decimal

import pytest

from critisizer.models import (
    Aspect,
    Evidence,
    Indicator,
    Policy,
    RubricVersion,
    RubricWeight,
)
from critisizer.scorecard import indicator_multiplier, load_active_rubric, score_policy
from critisizer.scoring.engine import ScoringError

CODES = [
    "outcome_failure",
    "cost_waste",
    "transparency_gap",
    "ground_level_harm",
    "legal_challenges",
    "equity_impact",
]


@pytest.fixture
def aspects(session):
    made = {}
    for code in CODES:
        aspect = Aspect(code=code, name=code, definition="test")
        session.add(aspect)
        made[code] = aspect
    version = RubricVersion(label="test-v1", min_ratings=5, is_active=True)
    session.add(version)
    session.flush()
    for aspect in made.values():
        session.add(
            RubricWeight(
                rubric_version_id=version.id,
                aspect_id=aspect.id,
                weight=Decimal(1),
            )
        )
    session.flush()
    return made


def make_policy(session, slug):
    policy = Policy(slug=slug, name=slug, year=2024, summary="test")
    session.add(policy)
    session.flush()
    return policy


def add_indicator(session, policy, aspect, score, multipliers, weight=1):
    indicator = Indicator(
        policy_id=policy.id,
        aspect_id=aspect.id,
        name=f"{aspect.code} indicator",
        score=Decimal(score),
        weight=Decimal(weight),
    )
    session.add(indicator)
    session.flush()
    for n, mult in enumerate(multipliers):
        session.add(
            Evidence(
                indicator_id=indicator.id,
                source_url=f"https://example.org/{indicator.id}/{n}",
                source_title="test",
                source_tier=1,
                verification_multiplier=Decimal(str(mult)),
                content_hash=f"{indicator.id}-{n}",
            )
        )
    session.flush()


def fill_policy(session, aspects, slug, rows):
    """rows: {aspect code: (score, [evidence multipliers])}"""
    policy = make_policy(session, slug)
    for code, (score, multipliers) in rows.items():
        add_indicator(session, policy, aspects[code], score, multipliers)
    return policy


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