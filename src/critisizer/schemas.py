from datetime import date, datetime

from pydantic import BaseModel

REVIEW_NOTE = "AI-drafted, human-reviewed"


class EvidenceOut(BaseModel):
    source_url: str
    source_title: str
    source_tier: int
    multiplier: float
    excluded: bool
    quote: str | None = None
    outlet: str | None = None


class IndicatorOut(BaseModel):
    name: str
    description: str | None
    score: float
    weight: float
    evidence: list[EvidenceOut]
    model: str | None = None
    prompt_version: str | None = None
    evidence_status: str = "realised"
    projection_source: str | None = None


class AspectScoreOut(BaseModel):
    code: str
    name: str
    # None while the aspect is unresolved. 0.0 with status
    # "no_negative_evidence" means a reviewer found none in the collected sources.
    score: float | None
    indicators: list[IndicatorOut]
    # unresolved | scored | no_negative_evidence | projected | too_early
    status: str = "unresolved"
    review_reason: str | None = None
    review_date: date | None = None


class PolicySummary(BaseModel):
    slug: str
    name: str
    year: int
    summary: str | None
    # True once at least one aspect is resolved.
    scored: bool = True
    # True only when all aspects are resolved; the overall rating exists only then.
    # True when enough aspects rest on realised evidence (method v2: at least 4).
    rated: bool = False
    aspects_resolved: int = 0
    # Aspects on realised evidence; these make up the rating.
    aspects_assessed: int = 0
    aspects_total: int = 0
    method_version: str = "v2"
    overall_rating: float | None
    spike_flag: bool
    people_rating: float | None
    people_rating_count: int
    people_rating_visible: bool


class PolicyDetail(PolicySummary):
    rubric_label: str
    expert_average: float | None
    aspects: list[AspectScoreOut]
    # Aspects that have at least one approved indicator.
    aspects_reviewed: int = 0
    # How much collected material the numbers rest on.
    source_count: int = 0
    outlet_count: int = 0
    review_note: str = REVIEW_NOTE


class SnapshotOut(BaseModel):
    week: date
    rubric_label: str
    aspect_scores: dict[str, float]
    expert_average: float
    people_rating: float | None
    people_rating_count: int
    overall_rating: float
    spike_flag: bool
    computed_at: datetime
