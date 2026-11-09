"""Run the fixed query for one policy and store what we could read."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from critisizer.evidence.gdelt import GdeltClient
from critisizer.evidence.outlets import outlet_for
from critisizer.evidence.query import QUERY_VERSION, build_query, search_phrase
from critisizer.evidence.text import fetch_article_text, make_excerpt
from critisizer.models import EvidenceRun, Policy, SourceItem

MAX_ITEMS_PER_RUN = 20
MIN_ITEMS_TO_SCORE = 3
MIN_OUTLETS_TO_SCORE = 2


@dataclass
class CollectReport:
    run_id: int
    found: int
    stored: int
    skipped: Counter = field(default_factory=Counter)


def collect_for_policy(
    session: Session,
    policy: Policy,
    client: GdeltClient,
    fetch: Callable[[str], str | None] = fetch_article_text,
) -> CollectReport:
    phrase = search_phrase(policy.name, policy.slug)
    query = build_query(phrase)
    raw, articles = client.search(query)

    run = EvidenceRun(
        policy_id=policy.id,
        query_version=QUERY_VERSION,
        query_text=query,
        source_api="gdelt_doc_v2",
        result_count=len(articles),
        raw=json.loads(raw) if raw.strip() else None,
    )
    session.add(run)
    session.flush()

    report = CollectReport(run_id=run.id, found=len(articles), stored=0)
    seen_urls: set[str] = set()
    for article in articles:
        if report.stored >= MAX_ITEMS_PER_RUN:
            break
        outlet = outlet_for(article.domain)
        if outlet is None:
            report.skipped["not_allowed"] += 1
            continue
        if article.url in seen_urls:
            report.skipped["duplicate"] += 1
            continue
        seen_urls.add(article.url)
        if session.scalar(
            select(SourceItem.id).where(
                SourceItem.policy_id == policy.id, SourceItem.url == article.url
            )
        ):
            report.skipped["duplicate"] += 1
            continue
        try:
            text = fetch(article.url)
        except Exception:  # noqa: BLE001 - any fetch failure just skips the item
            text = None
        if not text:
            report.skipped["fetch_failed"] += 1
            continue
        excerpt = make_excerpt(article.title, text, phrase)
        if excerpt is None:
            report.skipped["no_mention"] += 1
            continue
        content_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        if session.scalar(
            select(SourceItem.id).where(
                SourceItem.policy_id == policy.id,
                SourceItem.content_hash == content_hash,
            )
        ):
            report.skipped["duplicate"] += 1
            continue
        session.add(
            SourceItem(
                run_id=run.id,
                policy_id=policy.id,
                url=article.url,
                outlet=outlet.name,
                published_at=article.published_at,
                excerpt=excerpt,
                content_hash=content_hash,
            )
        )
        session.flush()
        report.stored += 1
    return report


def enough_to_score(session: Session, policy_id: int) -> bool:
    """The method's floor: at least 3 excerpts from at least 2 outlets."""
    items, outlets = session.execute(
        select(func.count(SourceItem.id), func.count(func.distinct(SourceItem.outlet)))
        .where(SourceItem.policy_id == policy_id)
    ).one()
    return items >= MIN_ITEMS_TO_SCORE and outlets >= MIN_OUTLETS_TO_SCORE