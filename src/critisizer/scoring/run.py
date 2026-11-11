"""Score one policy: python -m critisizer.scoring.run --slug X --scorer ollama."""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from critisizer.db import SessionLocal
from critisizer.evidence.collect import enough_to_score
from critisizer.evidence.outlets import outlet_for
from critisizer.models import Policy, SourceItem
from critisizer.scoring import gemini, hosted, ollama
from critisizer.scoring.cache import CachedScorer
from critisizer.scoring.citations import resolve_citations
from critisizer.scoring.contract import (
    ASPECT_CODES,
    IndicatorDraft,
    Scorer,
    ScorerError,
    ScoringRequest,
    SourceExcerpt,
)
from critisizer.scoring.drafts import store_drafts
from critisizer.scoring.fake import FakeScorer
from critisizer.scoring.prompt import ASPECT_PROMPT_VERSION, PROMPT_VERSION
from critisizer.scoring.verifier import AnswerError, parse_answer, verify_answer

logger = logging.getLogger("critisizer.scoring")

HAND_SCORES = Path("docs/hand-scores.md")
DEFAULT_TOKEN_BUDGET = 150_000
MAX_PER_ASPECT = 3  # a looping model cannot flood one aspect
# Errors that mean "stop asking today": more calls would only be refused.
QUOTA_ERRORS = {"gemini_http_429", "daily_cap_reached", "budget_exhausted"}


@dataclass
class ScoreReport:
    status: str  # "scored" or "not_enough_evidence"
    accepted: int = 0
    rejected: int = 0


@dataclass
class AspectOutcome:
    aspect: str
    # "accepted": at least one draft passed the verifier
    # "none": the model said there is no finding for this aspect
    # "rejected": the model gave findings but all failed verification
    # "failed": no usable answer (timeout, bad JSON)
    # "quota": the scorer's quota or budget ran out on this aspect
    # "skipped": not asked, because an earlier aspect hit the quota
    status: str
    accepted: int = 0
    rejected: int = 0


@dataclass
class AspectReport:
    status: str  # "scored" or "not_enough_evidence"
    outcomes: list[AspectOutcome] = field(default_factory=list)

    @property
    def accepted(self) -> int:
        return sum(o.accepted for o in self.outcomes)

    @property
    def rejected(self) -> int:
        return sum(o.rejected for o in self.outcomes)

    @property
    def usable(self) -> int:
        """Aspects where the model gave a well-formed, verified or empty answer."""
        return sum(1 for o in self.outcomes if o.status in ("accepted", "none"))


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
    """The old single-pass method (prompt_v3). Kept so earlier runs can be repeated."""
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


def force_aspect(raw: str, aspect: str) -> str:
    """The code, not the model, decides which aspect an answer belongs to. Also
    caps the number of indicators, so a looping model cannot flood one aspect."""
    try:
        data = json.loads(raw)
    except ValueError:
        return raw
    items = data.get("indicators") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return raw
    items = items[:MAX_PER_ASPECT]
    for item in items:
        if isinstance(item, dict):
            item["aspect"] = aspect
    data["indicators"] = items
    return json.dumps(data)


def _score_one_aspect(
    policy: Policy, scorer: Scorer, excerpts: list[SourceExcerpt], code: str
) -> tuple[AspectOutcome, list[IndicatorDraft]]:
    request = ScoringRequest(policy.name, policy.year, excerpts, aspect=code)
    try:
        raw = scorer.score(request)
    except ScorerError as exc:
        logger.warning("%s: scorer failed (%s)", code, exc)
        status = "quota" if str(exc) in QUOTA_ERRORS else "failed"
        return AspectOutcome(code, status), []
    raw = force_aspect(resolve_citations(raw, excerpts), code)
    try:
        items = parse_answer(raw)
    except AnswerError as exc:
        logger.warning("%s: unusable answer (%s)", code, exc)
        return AspectOutcome(code, "failed"), []
    if not items:
        return AspectOutcome(code, "none"), []
    result = verify_answer(raw, excerpts, (code,))
    for item in result.rejected:
        logger.info("rejected: %s", item)
    status = "accepted" if result.accepted else "rejected"
    outcome = AspectOutcome(
        code, status, len(result.accepted), len(result.rejected)
    )
    return outcome, result.accepted


def score_policy_by_aspect(
    session: Session, policy: Policy, scorer: Scorer
) -> AspectReport:
    """One call per aspect (prompt_v4). All accepted drafts are stored together,
    because storing replaces earlier drafts of the same model and prompt version.
    If the scorer's quota runs out, the remaining aspects are skipped, so a rerun
    later can fill them in without hammering the service."""
    if not enough_to_score(session, policy.id):
        return AspectReport("not_enough_evidence")
    excerpts = load_excerpts(session, policy.id)
    outcomes: list[AspectOutcome] = []
    drafts: list[IndicatorDraft] = []
    stopped = False
    for code in ASPECT_CODES:
        if stopped:
            outcomes.append(AspectOutcome(code, "skipped"))
            continue
        outcome, accepted = _score_one_aspect(policy, scorer, excerpts, code)
        outcomes.append(outcome)
        drafts.extend(accepted)
        logger.info(
            "  %-18s %-9s accepted=%d rejected=%d",
            code,
            outcome.status,
            outcome.accepted,
            outcome.rejected,
        )
        if outcome.status == "quota":
            stopped = True
            logger.warning("quota reached: remaining aspects skipped, rerun later")
    if all(o.status in ("failed", "quota", "skipped") for o in outcomes):
        raise ScorerError("all_aspects_failed")
    store_drafts(
        session, policy.id, drafts, excerpts, scorer.name, ASPECT_PROMPT_VERSION
    )
    return AspectReport("scored", outcomes)


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
    elif kind == "gemini":
        ledger = gemini.CallLedger(
            gemini.CALL_LEDGER,
            int(
                os.environ.get(
                    "CRITISIZER_GEMINI_DAILY_CAP", gemini.DEFAULT_DAILY_CAP
                )
            ),
        )
        inner = gemini.GeminiScorer(
            gemini.load_api_key(), ledger, model or gemini.DEFAULT_MODEL
        )
    else:
        raise ScorerError("unknown_scorer")
    return CachedScorer(inner)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="critisizer.scoring.run")
    parser.add_argument("--slug", required=True)
    parser.add_argument(
        "--scorer",
        choices=["fake", "ollama", "anthropic", "gemini"],
        required=True,
    )
    parser.add_argument("--model")
    parser.add_argument("--mode", choices=["aspect", "single"], default="aspect")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    try:
        scorer = make_scorer(args.scorer, args.model)
        with SessionLocal() as session:
            policy = session.scalar(select(Policy).where(Policy.slug == args.slug))
            if policy is None:
                logger.error("no such policy: %s", args.slug)
                raise SystemExit(1)
            if args.mode == "single":
                report: ScoreReport | AspectReport = score_policy_excerpts(
                    session, policy, scorer
                )
            else:
                report = score_policy_by_aspect(session, policy, scorer)
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
    if isinstance(report, AspectReport) and report.outcomes:
        logger.info(
            "%s: usable aspect answers %d of %d",
            args.slug,
            report.usable,
            len(report.outcomes),
        )


if __name__ == "__main__":
    main()