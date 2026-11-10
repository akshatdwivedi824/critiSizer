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
    SourceItem,
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


def scored_policy_ids(session: Session) -> set[int]:
    """Policies with at least one approved indicator. The rest are 'not yet
    scored'. Drafts never count until a reviewer approves them."""
    approved = select(Indicator.policy_id).where(Indicator.status == "approved")
    return set(session.scalars(approved.distinct()))


def _is_scored(session: Session, policy_id: int) -> bool:
    found = session.scalar(
        select(Indicator.id)
        .where(Indicator.policy_id == policy_id, Indicator.status == "approved")
        .limit(1)
    )
    return found is not None


def indicator_multiplier(evidence: list[Evidence]) -> Decimal:
    """An indicator stands on its best-verified evidence; no evidence means 0."""
    values = [Decimal(str(e.verification_multiplier)) for e in evidence]
    return max(values, default=Decimal(0))


def score_policy(session: Session, policy_id: int, rubric: Rubric) -> OverallResult:
    aspects = session.execute(select(Aspect.id, Aspect.code)).all()
    indicators = session.scalars(
        select(Indicator).where(
            Indicator.policy_id == policy_id, Indicator.status == "approved"
        )
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
        if not inputs:
            # No approved indicators for this aspect: nothing documented, counts 0.
            aspect_scores[code] = Decimal(0)
        else:
            # Indicators exist: keep the strict rule (None if no valid evidence).
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
        "scored": True,
        "overall_rating": _r(result.overall_rating),
        "spike_flag": result.spike_flag,
        "people_rating": (
            None if result.people_rating is None else _r(result.people_rating)
        ),
        "people_rating_count": result.people_rating_count,
        "people_rating_visible": result.people_rating is not None,
    }


def _unscored_fields(policy: Policy) -> dict:
    return {
        "slug": policy.slug,
        "name": policy.name,
        "year": policy.year,
        "summary": policy.summary,
        "scored": False,
        "overall_rating": None,
        "spike_flag": False,
        "people_rating": None,
        "people_rating_count": 0,
        "people_rating_visible": False,
    }


def build_policy_summary(
    session: Session, policy: Policy, rubric: Rubric
) -> PolicySummary:
    if not _is_scored(session, policy.id):
        return PolicySummary(**_unscored_fields(policy))
    result = score_policy(session, policy.id, rubric)
    return PolicySummary(**_summary_fields(policy, result))


def build_policy_detail(
    session: Session, policy: Policy, rubric: Rubric
) -> PolicyDetail:
    aspects = session.scalars(select(Aspect).order_by(Aspect.id)).all()
    if not _is_scored(session, policy.id):
        return PolicyDetail(
            **_unscored_fields(policy),
            rubric_label=rubric.label,
            expert_average=None,
            aspects=[],
            aspects_reviewed=0,
            aspects_total=len(aspects),
        )
    result = score_policy(session, policy.id, rubric)
    indicators = session.scalars(
        select(Indicator)
        .where(Indicator.policy_id == policy.id, Indicator.status == "approved")
        .order_by(Indicator.id)
    ).all()
    evidence_rows = session.execute(
        select(Evidence, SourceItem.outlet)
        .outerjoin(SourceItem, SourceItem.id == Evidence.source_item_id)
        .where(Evidence.indicator_id.in_([i.id for i in indicators]))
        .order_by(Evidence.id)
    ).all()

    ev_by_ind: dict[int, list[tuple[Evidence, str | None]]] = {}
    for ev, outlet in evidence_rows:
        ev_by_ind.setdefault(ev.indicator_id, []).append((ev, outlet))

    aspect_out = []
    for aspect in aspects:
        items = [
            IndicatorOut(
                name=ind.name,
                description=ind.description,
                score=float(ind.score),
                weight=float(ind.weight),
                model=ind.model,
                prompt_version=ind.prompt_version,
                evidence=[
                    EvidenceOut(
                        source_url=ev.source_url,
                        source_title=ev.source_title,
                        source_tier=ev.source_tier,
                        multiplier=float(ev.verification_multiplier),
                        excluded=ev.verification_multiplier == 0,
                        quote=ev.quote,
                        outlet=outlet,
                    )
                    for ev, outlet in ev_by_ind.get(ind.id, [])
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
        aspects_reviewed=sum(1 for a in aspect_out if a.indicators),
        aspects_total=len(aspect_out),
    )