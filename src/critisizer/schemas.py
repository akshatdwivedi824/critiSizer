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


class AspectScoreOut(BaseModel):
    code: str
    name: str
    score: float
    indicators: list[IndicatorOut]


class PolicySummary(BaseModel):
    slug: str
    name: str
    year: int
    summary: str | None
    scored: bool = True
    overall_rating: float | None
    spike_flag: bool
    people_rating: float | None
    people_rating_count: int
    people_rating_visible: bool


class PolicyDetail(PolicySummary):
    rubric_label: str
    expert_average: float | None
    aspects: list[AspectScoreOut]
    # How much of the scorecard a human has reviewed. An aspect with no approved
    # indicator counts as 0, so a low number can mean "not reviewed yet".
    aspects_reviewed: int = 0
    aspects_total: int = 0
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