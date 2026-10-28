from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from critisizer.models import Aspect, Evidence, Indicator, Policy, Rating, User


def make_policy(session):
    policy = Policy(slug="test-policy", name="Test policy", year=2024, summary="x")
    session.add(policy)
    session.flush()
    return policy


def make_user(session, email="a@example.org"):
    user = User(email=email, password_hash="not-a-real-hash")
    session.add(user)
    session.flush()
    return user


def make_indicator(session, policy, score="50"):
    aspect = Aspect(code="a1", name="Aspect 1", definition="test")
    session.add(aspect)
    session.flush()
    indicator = Indicator(
        policy_id=policy.id, aspect_id=aspect.id, name="i1", score=Decimal(score)
    )
    session.add(indicator)
    session.flush()
    return indicator


def make_evidence(indicator, multiplier="0.80", content_hash="abc"):
    return Evidence(
        indicator_id=indicator.id,
        source_url="https://example.org/a",
        source_title="Fictional source",
        source_tier=3,
        verification_multiplier=Decimal(multiplier),
        content_hash=content_hash,
    )


def test_valid_rows_are_accepted(session):
    policy = make_policy(session)
    user = make_user(session)
    indicator = make_indicator(session, policy)
    session.add(make_evidence(indicator))
    session.add(Rating(user_id=user.id, policy_id=policy.id, value=Decimal(70)))
    session.flush()


def test_second_rating_from_same_user_is_rejected(session):
    policy = make_policy(session)
    user = make_user(session)
    session.add(Rating(user_id=user.id, policy_id=policy.id, value=Decimal(70)))
    session.flush()
    session.add(Rating(user_id=user.id, policy_id=policy.id, value=Decimal(20)))
    with pytest.raises(IntegrityError, match="ratings_user_id_policy_id_key"):
        session.flush()


def test_score_above_100_is_rejected(session):
    policy = make_policy(session)
    with pytest.raises(IntegrityError, match="ck_indicators_score_range"):
        make_indicator(session, policy, score="101")


def test_multiplier_outside_allowed_set_is_rejected(session):
    policy = make_policy(session)
    indicator = make_indicator(session, policy)
    session.add(make_evidence(indicator, multiplier="0.70"))
    with pytest.raises(IntegrityError, match="ck_evidence_multiplier_allowed"):
        session.flush()


def test_same_evidence_hash_twice_is_rejected(session):
    policy = make_policy(session)
    indicator = make_indicator(session, policy)
    session.add(make_evidence(indicator, content_hash="same"))
    session.flush()
    session.add(make_evidence(indicator, content_hash="same"))
    with pytest.raises(IntegrityError, match="evidence_indicator_id_content_hash_key"):
        session.flush()