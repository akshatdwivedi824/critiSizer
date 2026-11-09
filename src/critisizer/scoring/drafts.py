"""Saves verified drafts. They are 'ai_draft' and never count until approved."""

import hashlib
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from critisizer.models import Aspect, Evidence, Indicator
from critisizer.scoring.contract import IndicatorDraft, SourceExcerpt

# Set by code from the source's tier; the scorer never chooses it.
TIER_MULTIPLIER = {
    1: Decimal("1.00"),
    2: Decimal("1.00"),
    3: Decimal("0.80"),
    4: Decimal("0.00"),
}


def _hash(url: str, quote: str) -> str:
    return hashlib.sha256(f"{url}\n{quote}".encode()).hexdigest()


def store_drafts(
    session: Session,
    policy_id: int,
    drafts: list[IndicatorDraft],
    excerpts: list[SourceExcerpt],
    model: str,
    prompt_version: str,
) -> list[Indicator]:
    """Save drafts as ai_draft indicators with their quotes. Running again
    replaces the earlier drafts of the same model and prompt version, so it is
    safe to repeat. The caller commits."""
    session.execute(
        delete(Indicator).where(
            Indicator.policy_id == policy_id,
            Indicator.status == "ai_draft",
            Indicator.model == model,
            Indicator.prompt_version == prompt_version,
        )
    )
    aspects = dict(session.execute(select(Aspect.code, Aspect.id)).all())
    by_id = {e.id: e for e in excerpts}

    stored = []
    for draft in drafts:
        indicator = Indicator(
            policy_id=policy_id,
            aspect_id=aspects[draft.aspect],
            name=draft.name,
            score=Decimal(draft.score),
            weight=Decimal(1),
            description=draft.description,
            status="ai_draft",
            model=model,
            prompt_version=prompt_version,
        )
        session.add(indicator)
        session.flush()
        seen = set()
        for quote in draft.quotes:
            source = by_id[quote.source_id]
            digest = _hash(source.url, quote.text)
            if digest in seen:
                continue
            seen.add(digest)
            session.add(
                Evidence(
                    indicator_id=indicator.id,
                    source_url=source.url,
                    source_title=source.title[:300],
                    source_tier=source.tier,
                    verification_multiplier=TIER_MULTIPLIER[source.tier],
                    content_hash=digest,
                    quote=quote.text,
                    source_item_id=source.item_id,
                )
            )
        stored.append(indicator)
    session.flush()
    return stored