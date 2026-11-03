from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from critisizer.formatting import round_score
from critisizer.models import (
    Aspect,
    Evidence,
    Indicator,
    Policy,
    Rating,
    RubricVersion,
    RubricWeight,
)
from critisizer.schemas import (
    AspectScoreOut,
    EvidenceOut,
    IndicatorOut,
    PolicyDetail,
    PolicySummary,
)
from critisizer.scoring.engine import (
    IndicatorInput,
    OverallResult,
    RatingInput,
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

    rating_rows = session.execute(
        select(Rating.value, Rating.status).where(Rating.policy_id == policy_id)
    ).all()
    ratings = [RatingInput(value=Decimal(str(v)), status=s) for v, s in rating_rows]
    return overall_rating(aspect_scores, ratings, rubric)


def _r(value: Decimal) -> float:
    return float(round_score(value))


def _summary_fields(policy: Policy, result: OverallResult) -> dict:
    return {
        "slug": policy.slug,
        "name": policy.name,
        "year": policy.year,
        "summary": policy.summary,
        "overall_rating": _r(result.overall_rating),
        "spike_flag": result.spike_flag,
        "people_rating": (
            None if result.people_rating is None else _r(result.people_rating)
        ),
        "people_rating_count": result.people_rating_count,
        "people_rating_visible": result.people_rating is not None,
    }


def build_policy_summary(
    session: Session, policy: Policy, rubric: Rubric
) -> PolicySummary:
    result = score_policy(session, policy.id, rubric)
    return PolicySummary(**_summary_fields(policy, result))


def build_policy_detail(
    session: Session, policy: Policy, rubric: Rubric
) -> PolicyDetail:
    result = score_policy(session, policy.id, rubric)
    aspects = session.scalars(select(Aspect).order_by(Aspect.id)).all()
    indicators = session.scalars(
        select(Indicator)
        .where(Indicator.policy_id == policy.id)
        .order_by(Indicator.id)
    ).all()
    evidence = session.scalars(
        select(Evidence)
        .where(Evidence.indicator_id.in_([i.id for i in indicators]))
        .order_by(Evidence.id)
    ).all()

    ev_by_ind: dict[int, list[Evidence]] = {}
    for ev in evidence:
        ev_by_ind.setdefault(ev.indicator_id, []).append(ev)

    aspect_out = []
    for aspect in aspects:
        items = [
            IndicatorOut(
                name=ind.name,
                description=ind.description,
                score=float(ind.score),
                weight=float(ind.weight),
                evidence=[
                    EvidenceOut(
                        source_url=ev.source_url,
                        source_title=ev.source_title,
                        source_tier=ev.source_tier,
                        multiplier=float(ev.verification_multiplier),
                        excluded=ev.verification_multiplier == 0,
                    )
                    for ev in ev_by_ind.get(ind.id, [])
                ],
            )
            for ind in indicators
            if ind.aspect_id == aspect.id
        ]
        aspect_out.append(
            AspectScoreOut(
                code=aspect.code,
                name=aspect.name,
                score=_r(result.aspect_scores[aspect.code]),
                indicators=items,
            )
        )

    return PolicyDetail(
        **_summary_fields(policy, result),
        rubric_label=result.rubric_label,
        expert_average=_r(result.expert_average),
        aspects=aspect_out,
    )