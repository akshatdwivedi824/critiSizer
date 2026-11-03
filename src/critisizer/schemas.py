from pydantic import BaseModel


class EvidenceOut(BaseModel):
    source_url: str
    source_title: str
    source_tier: int
    multiplier: float
    excluded: bool


class IndicatorOut(BaseModel):
    name: str
    description: str | None
    score: float
    weight: float
    evidence: list[EvidenceOut]


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
    overall_rating: float
    spike_flag: bool
    people_rating: float | None
    people_rating_count: int
    people_rating_visible: bool


class PolicyDetail(PolicySummary):
    rubric_label: str
    expert_average: float
    aspects: list[AspectScoreOut]
