from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from critisizer.formatting import round_score
from critisizer.models import (
    Aspect,
    AspectReview,
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
    ScoringError,
    aspect_score,
    overall_rating,
)

# A reviewer may record "no negative evidence found" only with at least this
# much collected material; "none found" in two articles says little.
MIN_SOURCES = 3
MIN_OUTLETS = 2


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
    """Policies with at least one approved indicator. Drafts never count until a
    reviewer approves them."""
    approved = select(Indicator.policy_id).where(Indicator.status == "approved")
    return set(session.scalars(approved.distinct()))


@dataclass(frozen=True)
class Progress:
    """Which aspects of a policy a human has resolved.

    An aspect is resolved by an approved indicator (scored) or by a reviewer
    recording that the collected sources hold no negative evidence for it.
    """

    scored: frozenset[str]
    reviewed: frozenset[str]
    total: int

    @property
    def resolved(self) -> int:
        return len(self.scored | self.reviewed)

    @property
    def rated(self) -> bool:
        return self.total > 0 and self.resolved == self.total

    def status(self, code: str) -> str:
        if code in self.scored:
            return "scored"
        if code in self.reviewed:
            return "no_negative_evidence"
        return "unresolved"


def policy_progress(session: Session, policy_id: int) -> Progress:
    scored = set(
        session.scalars(
            select(Aspect.code)
            .join(Indicator, Indicator.aspect_id == Aspect.id)
            .where(Indicator.policy_id == policy_id, Indicator.status == "approved")
        )
    )
    reviewed = set(
        session.scalars(
            select(Aspect.code)
            .join(AspectReview, AspectReview.aspect_id == Aspect.id)
            .where(AspectReview.policy_id == policy_id)
        )
    )
    total = session.scalar(select(func.count(Aspect.id))) or 0
    return Progress(frozenset(scored), frozenset(reviewed), total)


def evidence_depth(session: Session, policy_id: int) -> tuple[int, int]:
    """(collected sources, distinct outlets) for a policy."""
    sources, outlets = session.execute(
        select(
            func.count(SourceItem.id), func.count(func.distinct(SourceItem.outlet))
        ).where(SourceItem.policy_id == policy_id)
    ).one()
    return sources, outlets


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
            # No approved indicator: either a reviewer recorded "no negative
            # evidence found" (a reviewed 0) or the policy is not rated yet.
            aspect_scores[code] = Decimal(0)
        else:
            # Indicators exist: keep the strict rule (error if no valid evidence).
            aspect_scores[code] = aspect_score(inputs)

    rating_rows = session.execute(
        select(Rating.value, Rating.status).where(Rating.policy_id == policy_id)
    ).all()
    ratings = [RatingInput(value=Decimal(str(v)), status=s) for v, s in rating_rows]
    return overall_rating(aspect_scores, ratings, rubric)


def _r(value: Decimal) -> float:
    return float(round_score(value))


def _fields(policy: Policy, progress: Progress, result: OverallResult | None) -> dict:
    """Summary fields. The overall rating, spike flag and people rating exist
    only for a fully resolved policy (result is not None)."""
    return {
        "slug": policy.slug,
        "name": policy.name,
        "year": policy.year,
        "summary": policy.summary,
        "scored": progress.resolved > 0,
        "rated": result is not None,
        "aspects_resolved": progress.resolved,
        "aspects_total": progress.total,
        "overall_rating": None if result is None else _r(result.overall_rating),
        "spike_flag": False if result is None else result.spike_flag,
        "people_rating": (
            None
            if result is None or result.people_rating is None
            else _r(result.people_rating)
        ),
        "people_rating_count": 0 if result is None else result.people_rating_count,
        "people_rating_visible": result is not None
        and result.people_rating is not None,
    }


def build_policy_summary(
    session: Session, policy: Policy, rubric: Rubric
) -> PolicySummary:
    progress = policy_progress(session, policy.id)
    result = score_policy(session, policy.id, rubric) if progress.rated else None
    return PolicySummary(**_fields(policy, progress, result))


def _partial_score(
    indicators: list[Indicator], ev_by_ind: dict[int, list[Evidence]]
) -> Decimal | None:
    inputs = [
        IndicatorInput(
            score=Decimal(str(i.score)),
            weight=Decimal(str(i.weight)),
            multiplier=indicator_multiplier(ev_by_ind.get(i.id, [])),
        )
        for i in indicators
    ]
    try:
        return aspect_score(inputs)
    except ScoringError:
        return None


def build_policy_detail(
    session: Session, policy: Policy, rubric: Rubric
) -> PolicyDetail:
    aspects = session.scalars(select(Aspect).order_by(Aspect.id)).all()
    progress = policy_progress(session, policy.id)
    sources, outlets = evidence_depth(session, policy.id)
    depth = {"source_count": sources, "outlet_count": outlets}

    if progress.resolved == 0:
        return PolicyDetail(
            **_fields(policy, progress, None),
            rubric_label=rubric.label,
            expert_average=None,
            aspects=[],
            aspects_reviewed=0,
            **depth,
        )

    result = score_policy(session, policy.id, rubric) if progress.rated else None
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
    reasons = dict(
        session.execute(
            select(Aspect.code, AspectReview.reason)
            .join(AspectReview, AspectReview.aspect_id == Aspect.id)
            .where(AspectReview.policy_id == policy.id)
        ).all()
    )

    ev_pairs: dict[int, list[tuple[Evidence, str | None]]] = {}
    for ev, outlet in evidence_rows:
        ev_pairs.setdefault(ev.indicator_id, []).append((ev, outlet))
    ev_by_ind = {k: [ev for ev, _ in v] for k, v in ev_pairs.items()}

    aspect_out = []
    for aspect in aspects:
        status = progress.status(aspect.code)
        own = [ind for ind in indicators if ind.aspect_id == aspect.id]
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
                    for ev, outlet in ev_pairs.get(ind.id, [])
                ],
            )
            for ind in own
        ]
        if result is not None:
            score: float | None = _r(result.aspect_scores[aspect.code])
        elif own:
            partial = _partial_score(own, ev_by_ind)
            score = None if partial is None else _r(partial)
        elif status == "no_negative_evidence":
            score = 0.0
        else:
            score = None
        aspect_out.append(
            AspectScoreOut(
                code=aspect.code,
                name=aspect.name,
                score=score,
                indicators=items,
                status=status,
                review_reason=reasons.get(aspect.code),
            )
        )

    return PolicyDetail(
        **_fields(policy, progress, result),
        rubric_label=result.rubric_label if result else rubric.label,
        expert_average=None if result is None else _r(result.expert_average),
        aspects=aspect_out,
        aspects_reviewed=sum(1 for a in aspect_out if a.indicators),
        **depth,
    )
