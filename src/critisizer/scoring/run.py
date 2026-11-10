"""Score one policy: python -m critisizer.scoring.run --slug X --scorer ollama."""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from critisizer.db import SessionLocal
from critisizer.evidence.collect import enough_to_score
from critisizer.evidence.outlets import outlet_for
from critisizer.models import Policy, SourceItem
from critisizer.scoring import hosted, ollama
from critisizer.scoring.cache import CachedScorer
from critisizer.scoring.citations import resolve_citations
from critisizer.scoring.contract import (
    Scorer,
    ScorerError,
    ScoringRequest,
    SourceExcerpt,
)
from critisizer.scoring.drafts import store_drafts
from critisizer.scoring.fake import FakeScorer
from critisizer.scoring.prompt import PROMPT_VERSION
from critisizer.scoring.verifier import AnswerError, verify_answer

logger = logging.getLogger("critisizer.scoring")

HAND_SCORES = Path("docs/hand-scores.md")
DEFAULT_TOKEN_BUDGET = 150_000


@dataclass
class ScoreReport:
    status: str  # "scored" or "not_enough_evidence"
    accepted: int = 0
    rejected: int = 0


def hand_scores_ready(path: Path | None = None) -> bool:
    """Our baseline scores must be written (no '__' blanks) before a real model runs."""
    target = path or HAND_SCORES
    if not target.exists():
        return False
    text = target.read_text(encoding="utf-8")
    return "## " in text and "__" not in text


def load_excerpts(session: Session, policy_id: int) -> list[SourceExcerpt]:
    items = session.scalars(
        select(SourceItem)
        .where(SourceItem.policy_id == policy_id)
        .order_by(SourceItem.id)
    ).all()
    excerpts = []
    for number, item in enumerate(items, start=1):
        outlet = outlet_for(urlparse(item.url).netloc)
        published = item.published_at.date().isoformat() if item.published_at else None
        excerpts.append(
            SourceExcerpt(
                id=number,
                outlet=item.outlet,
                text=item.excerpt,
                tier=outlet.tier if outlet else 4,  # unknown outlet counts for 0
                url=item.url,
                title=item.excerpt.split("\n", 1)[0],
                published=published,
                item_id=item.id,
            )
        )
    return excerpts


def score_policy_excerpts(
    session: Session, policy: Policy, scorer: Scorer
) -> ScoreReport:
    if not enough_to_score(session, policy.id):
        return ScoreReport("not_enough_evidence")
    excerpts = load_excerpts(session, policy.id)
    request = ScoringRequest(policy.name, policy.year, excerpts)
    raw = resolve_citations(scorer.score(request), excerpts)
    try:
        result = verify_answer(raw, excerpts)
    except AnswerError as exc:
        raise ScorerError("bad_answer") from exc
    for item in result.rejected:
        logger.info("rejected: %s", item)
    store_drafts(
        session, policy.id, result.accepted, excerpts, scorer.name, PROMPT_VERSION
    )
    return ScoreReport("scored", len(result.accepted), len(result.rejected))


def make_scorer(kind: str, model: str | None = None) -> Scorer:
    if kind == "fake":
        return FakeScorer()
    if not hand_scores_ready(HAND_SCORES):
        raise ScorerError("hand_scores_missing")
    if kind == "ollama":
        inner: Scorer = ollama.OllamaScorer(model or ollama.DEFAULT_MODEL)
    elif kind == "anthropic":
        budget = hosted.Budget(
            hosted.LEDGER,
            int(os.environ.get("CRITISIZER_TOKEN_BUDGET", DEFAULT_TOKEN_BUDGET)),
        )
        inner = hosted.AnthropicScorer(
            os.environ.get("ANTHROPIC_API_KEY", ""),
            budget,
            model or hosted.DEFAULT_MODEL,
        )
    else:
        raise ScorerError("unknown_scorer")
    return CachedScorer(inner)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="critisizer.scoring.run")
    parser.add_argument("--slug", required=True)
    parser.add_argument(
        "--scorer", choices=["fake", "ollama", "anthropic"], required=True
    )
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        scorer = make_scorer(args.scorer, args.model)
        with SessionLocal() as session:
            policy = session.scalar(select(Policy).where(Policy.slug == args.slug))
            if policy is None:
                logger.error("no such policy: %s", args.slug)
                raise SystemExit(1)
            report = score_policy_excerpts(session, policy, scorer)
            session.commit()
    except ScorerError as exc:
        logger.error("scoring stopped: %s", exc)
        raise SystemExit(1) from exc
    logger.info(
        "%s: %s (accepted %d, rejected %d)",
        args.slug,
        report.status,
        report.accepted,
        report.rejected,
    )


if __name__ == "__main__":
    main()