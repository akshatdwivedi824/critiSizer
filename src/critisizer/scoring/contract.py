"""The scorer contract: what goes in, what comes out, who may score."""

from dataclasses import dataclass, field
from typing import Protocol

ASPECT_CODES = (
    "outcome_failure",
    "cost_waste",
    "transparency_gap",
    "ground_level_harm",
    "legal_challenges",
    "equity_impact",
)


class ScorerError(Exception):
    """The scorer could not produce an answer (network, budget, bad output)."""


@dataclass(frozen=True)
class SourceExcerpt:
    id: int  # the number the scorer cites; local to one request
    outlet: str
    text: str
    tier: int
    url: str
    title: str
    published: str | None = None
    item_id: int | None = None  # source_items.id when it came from the database


@dataclass(frozen=True)
class ScoringRequest:
    """Everything a scorer may see. There is deliberately no field for the
    policy's summary or stated aims: they must never reach the scorer.

    aspect is None for the old single-pass prompt (prompt_v3). When it is set,
    the scorer is asked about that one aspect only (prompt_v4)."""

    policy_name: str
    policy_year: int
    excerpts: list[SourceExcerpt]
    aspect: str | None = None


@dataclass(frozen=True)
class Quote:
    source_id: int
    text: str


@dataclass(frozen=True)
class IndicatorDraft:
    aspect: str
    name: str
    score: int
    description: str
    quotes: list[Quote] = field(default_factory=list)


class Scorer(Protocol):
    name: str

    def score(self, request: ScoringRequest) -> str:
        """Return the model's raw JSON answer (the shape in prompts/score_v1.txt)."""