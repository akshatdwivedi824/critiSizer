from decimal import Decimal

from critisizer.models import (
    Aspect,
    Evidence,
    Indicator,
    Policy,
    RubricVersion,
    RubricWeight,
)

CODES = [
    "outcome_failure",
    "cost_waste",
    "transparency_gap",
    "ground_level_harm",
    "legal_challenges",
    "equity_impact",
]


def make_aspects(session):
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
