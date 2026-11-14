from dataclasses import dataclass, field
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

# Method v2 (ADR 0004): an overall rating needs at least this many aspects that
# are assessed on realised evidence (approved realised indicators, or a
# reviewer's "no negative evidence"). Projected and "too early" aspects are
# shown but are not in the number.
MIN_ASSESSED = 4
METHOD_VERSION = "v2"


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
    """The state of each aspect of a policy, as a human has left it.

    scored:    an approved realised (or alleged) indicator exists
    reviewed:  a reviewer recorded "no negative evidence" in the sources
    projected: only approved projected indicators exist
    too_early: a reviewer recorded that it is too early to assess
    Anything else is unresolved.
    """

    scored: frozenset[str]
    reviewed: frozenset[str]
    total: int
    projected: frozenset[str] = field(default_factory=frozenset)
    too_early: frozenset[str] = field(default_factory=frozenset)

    @property
    def assessed(self) -> int:
        """Aspects on realised evidence: these make up the rating."""
        return len(self.scored | self.reviewed)

    @property
    def resolved(self) -> int:
        """Aspects in any stated state (anything but unresolved)."""
        return len(self.scored | self.reviewed | self.projected | self.too_early)

    @property
    def rated(self) -> bool:
        return self.total > 0 and self.assessed >= min(MIN_ASSESSED, self.total)

    def status(self, code: str) -> str:
        if code in self.scored:
            return "scored"
        if code in self.reviewed:
            return "no_negative_evidence"
        if code in self.projected:
            return "projected"
        if code in self.too_early:
            return "too_early"
        return "unresolved"


def policy_progress(session: Session, policy_id: int) -> Progress:
    def indicator_codes(*, projected: bool) -> set[str]:
        condition = (
            Indicator.evidence_status == "projected"
            if projected
            else Indicator.evidence_status != "projected"
        )
        return set(
            session.scalars(
                select(Aspect.code)
                .join(Indicator, Indicator.aspect_id == Aspect.id)
                .where(
                    Indicator.policy_id == policy_id,
                    Indicator.status == "approved",
                    condition,
                )
            )
        )

    def review_codes(outcome: str) -> set[str]:
        return set(
            session.scalars(
                select(Aspect.code)
                .join(AspectReview, AspectReview.aspect_id == Aspect.id)
                .where(
                    AspectReview.policy_id == policy_id,
                    AspectReview.outcome == outcome,
                )
            )
        )

    scored = indicator_codes(projected=False)
    projected = indicator_codes(projected=True) - scored
    reviewed = review_codes("no_negative_evidence") - scored
    too_early = review_codes("too_early") - scored - projected
    total = session.scalar(select(func.count(Aspect.id))) or 0
    return Progress(
        frozenset(scored),
        frozenset(reviewed),
        total,
        frozenset(projected),
        frozenset(too_early),
    )


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
    """The overall result over assessed aspects only (method v2).

    Projected and too-early aspects are not in the number.
    """
    progress = policy_progress(session, policy_id)
    aspects = session.execute(select(Aspect.id, Aspect.code)).all()
    indicators = session.scalars(
        select(Indicator).where(
            Indicator.policy_id == policy_id,
            Indicator.status == "approved",
            Indicator.evidence_status != "projected",
        )
    ).all()
    evidence = session.scalars(
        select(Evidence).where(Evidence.indicator_id.in_([i.id for i in indicators]))
    ).all()

    ev_by_ind: dict[int, list[Evidence]] = {}
    for ev in evidence:
        ev_by_ind.setdefault(ev.indicator_id, []).append(ev)

    aspect_scores: dict[str, Decimal | None] = {}
    for aspect_id, code in aspects:
        if code in progress.scored:
            inputs = [
                IndicatorInput(
                    score=Decimal(str(i.score)),
                    weight=Decimal(str(i.weight)),
                    multiplier=indicator_multiplier(ev_by_ind.get(i.id, [])),
                )
                for i in indicators
                if i.aspect_id == aspect_id
            ]
            # Strict rule kept: no valid evidence on an indicator is an error.
            aspect_scores[code] = aspect_score(inputs)
        elif code in progress.reviewed:
            # A reviewer found no negative evidence: a reviewed 0.
            aspect_scores[code] = Decimal(0)

    rating_rows = session.execute(
        select(Rating.value, Rating.status).where(Rating.policy_id == policy_id)
    ).all()
    ratings = [RatingInput(value=Decimal(str(v)), status=s) for v, s in rating_rows]
    return overall_rating(aspect_scores, ratings, rubric, partial=True)


def _r(value: Decimal) -> float:
    return float(round_score(value))


def _fields(policy: Policy, progress: Progress, result: OverallResult | None) -> dict:
    """Summary fields. The overall rating, spike flag and people rating exist
    only for a rated policy (result is not None)."""
    return {
        "slug": policy.slug,
        "name": policy.name,
        "year": policy.year,
        "summary": policy.summary,
        "scored": progress.resolved > 0,
        "rated": result is not None,
        "aspects_resolved": progress.resolved,
        "aspects_assessed": progress.assessed,
        "aspects_total": progress.total,
        "method_version": METHOD_VERSION,
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
    review_rows = session.execute(
        select(Aspect.code, AspectReview.reason, AspectReview.review_date)
        .join(AspectReview, AspectReview.aspect_id == Aspect.id)
        .where(AspectReview.policy_id == policy.id)
    ).all()
    reasons = {code: reason for code, reason, _ in review_rows}
    review_dates = {code: when for code, _, when in review_rows}

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
                evidence_status=ind.evidence_status,
                projection_source=ind.projection_source,
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
        # The shown score rests on realised indicators; a projected-only aspect
        # shows its projected score, flagged by its status.
        basis = [i for i in own if i.evidence_status != "projected"] or own
        if result is not None and aspect.code in result.aspect_scores:
            score: float | None = _r(result.aspect_scores[aspect.code])
        elif own:
            partial = _partial_score(basis, ev_by_ind)
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
                review_date=review_dates.get(aspect.code),
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