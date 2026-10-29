from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from critisizer.models import Aspect, Evidence, Indicator, RubricVersion, RubricWeight
from critisizer.scoring.engine import (
    IndicatorInput,
    OverallResult,
    Rubric,
    aspect_score,
    overall_rating,
)


def load_active_rubric(session: Session) -> Rubric:
    version = session.scalar(
        select(RubricVersion).where(RubricVersion.is_active.is_(True))
    )
    if version is None:
        raise LookupError("no active rubric version")
    rows = session.execute(
        select(Aspect.code, RubricWeight.weight)
        .join(RubricWeight, RubricWeight.aspect_id == Aspect.id)
        .where(RubricWeight.rubric_version_id == version.id)
    ).all()
    return Rubric(
        label=version.label,
        weights={code: Decimal(str(weight)) for code, weight in rows},
        min_ratings=version.min_ratings,
    )


def indicator_multiplier(evidence: list[Evidence]) -> Decimal:
    """An indicator stands on its best-verified evidence; no evidence means 0."""
    values = [Decimal(str(e.verification_multiplier)) for e in evidence]
    return max(values, default=Decimal(0))


def score_policy(session: Session, policy_id: int, rubric: Rubric) -> OverallResult:
    aspects = session.execute(select(Aspect.id, Aspect.code)).all()
    indicators = session.scalars(
        select(Indicator).where(Indicator.policy_id == policy_id)
    ).all()
    evidence = session.scalars(
        select(Evidence).where(Evidence.indicator_id.in_([i.id for i in indicators]))
    ).all()

    ev_by_ind: dict[int, list[Evidence]] = {}
    for ev in evidence:
        ev_by_ind.setdefault(ev.indicator_id, []).append(ev)

    aspect_scores = {}
    for aspect_id, code in aspects:
        inputs = [
            IndicatorInput(
                score=Decimal(str(i.score)),
                weight=Decimal(str(i.weight)),
                multiplier=indicator_multiplier(ev_by_ind.get(i.id, [])),
            )
            for i in indicators
            if i.aspect_id == aspect_id
        ]
        aspect_scores[code] = aspect_score(inputs)

    # No user ratings exist yet, so the people's rating is absent for now.
    return overall_rating(aspect_scores, [], rubric)