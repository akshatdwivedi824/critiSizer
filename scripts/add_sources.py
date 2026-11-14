"""Add hand-picked article URLs as source items for one policy.

GDELT only reaches back three months, so historical policies are fed from a
curated list instead. Everything after storage (scoring, review, export) is
unchanged.

List file: data/sources/<slug>.txt, one article per line:

    https://thehindu.com/...  |  Optional headline (overrides the page's own)
    # lines starting with # and blank lines are ignored

Run:
    uv run python scripts\\add_sources.py --slug farm-laws-2020 --dry-run
    uv run python scripts\\add_sources.py --slug farm-laws-2020
    uv run python scripts\\add_sources.py --slug farm-laws-2020 --retitle
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import trafilatura
from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.evidence.collect import enough_to_score
from critisizer.evidence.outlets import outlet_for
from critisizer.evidence.query import search_phrases
from critisizer.evidence.text import make_excerpt
from critisizer.models import EvidenceRun, Policy, SourceItem

logger = logging.getLogger("add_sources")
LIST_DIR = Path("data/sources")
SOURCE_API = "curated"
QUERY_VERSION = "curated_v1"

# (article text, page headline) - either may be None
Page = tuple[str | None, str | None]


def parse_list(text: str) -> list[tuple[str, str | None]]:
    """(url, title or None) for each usable line."""
    items: list[tuple[str, str | None]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url, _, title = line.partition("|")
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            continue
        items.append((url, title.strip() or None))
    return items


def title_from_url(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p and not p.isdigit()]
    slug = re.sub(r"\.html?$", "", parts[-1]) if parts else ""
    words = [w for w in slug.replace("_", "-").split("-") if not w.isdigit()]
    return " ".join(words).capitalize() or url


def fetch_page(url: str) -> Page:
    html = trafilatura.fetch_url(url)
    if not html:
        return None, None
    text = trafilatura.extract(html, include_comments=False, include_tables=False)
    meta = trafilatura.extract_metadata(html)
    title = (meta.title or "").strip() if meta else ""
    return text, (title or None)


def _fetch(fetch: Callable[[str], Page], url: str) -> Page:
    try:
        return fetch(url)
    except Exception:  # noqa: BLE001 - any fetch failure just skips the item
        return None, None


def _hash(excerpt: str) -> str:
    return hashlib.sha256(excerpt.encode("utf-8")).hexdigest()


def add_sources(
    session,
    policy: Policy,
    items: list[tuple[str, str | None]],
    *,
    dry_run: bool = False,
    retitle: bool = False,
    fetch: Callable[[str], Page] = fetch_page,
) -> Counter:
    phrases = search_phrases(policy.name, policy.slug)
    counts: Counter = Counter()
    run = None
    if not dry_run and not retitle:
        run = EvidenceRun(
            policy_id=policy.id,
            query_version=QUERY_VERSION,
            query_text="curated list",
            source_api=SOURCE_API,
            result_count=len(items),
            raw=None,
        )
        session.add(run)
        session.flush()

    seen: set[str] = set()
    for url, given_title in items:
        outlet = outlet_for(urlparse(url).netloc)
        if outlet is None:
            counts["not_allowed"] += 1
            logger.info("SKIP not_allowed   %s", url)
            continue
        if url in seen:
            counts["duplicate"] += 1
            logger.info("SKIP duplicate     %s", url)
            continue
        seen.add(url)
        existing = session.scalar(
            select(SourceItem).where(
                SourceItem.policy_id == policy.id, SourceItem.url == url
            )
        )

        if existing is not None:
            if not retitle:
                counts["duplicate"] += 1
                logger.info("SKIP duplicate     %s", url)
                continue
            _, page_title = _fetch(fetch, url)
            title = given_title or page_title
            if not title:
                counts["no_title"] += 1
                logger.info("SKIP no_title      %s", url)
                continue
            _, _, body = existing.excerpt.partition("\n")
            new_excerpt = f"{title}\n{body}"
            logger.info("%-7s %s -> %s", "WOULD" if dry_run else "RETITLE", url, title)
            counts["retitled"] += 1
            if not dry_run:
                existing.excerpt = new_excerpt
                existing.content_hash = _hash(new_excerpt)
                session.flush()
            continue

        if retitle:
            continue  # retitle never adds new items

        text, page_title = _fetch(fetch, url)
        if not text:
            counts["fetch_failed"] += 1
            logger.info("SKIP fetch_failed  %s", url)
            continue
        title = given_title or page_title or title_from_url(url)
        excerpt = make_excerpt(title, text, phrases)
        if excerpt is None:
            counts["no_mention"] += 1
            logger.info("SKIP no_mention    %s", url)
            continue
        content_hash = _hash(excerpt)
        if session.scalar(
            select(SourceItem.id).where(
                SourceItem.policy_id == policy.id,
                SourceItem.content_hash == content_hash,
            )
        ):
            counts["duplicate"] += 1
            logger.info("SKIP duplicate     %s", url)
            continue
        counts["stored"] += 1
        logger.info(
            "%-5s %-18s %s", "WOULD" if dry_run else "STORE", outlet.name, title
        )
        if not dry_run:
            session.add(
                SourceItem(
                    run_id=run.id,
                    policy_id=policy.id,
                    url=url,
                    outlet=outlet.name,
                    published_at=None,
                    excerpt=excerpt,
                    content_hash=content_hash,
                )
            )
            session.flush()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", action="append", required=True, help="repeat for several")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--retitle",
        action="store_true",
        help="fix the headline of items already stored (first excerpt line only)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with SessionLocal() as session:
        for slug in args.slug:
            policy = session.scalar(select(Policy).where(Policy.slug == slug))
            if policy is None:
                logger.warning("%s: no such policy in the database", slug)
                continue
            path = LIST_DIR / f"{slug}.txt"
            if not path.exists():
                logger.warning("%s: %s not found", slug, path)
                continue
            items = parse_list(path.read_text(encoding="utf-8"))
            counts = add_sources(
                session, policy, items, dry_run=args.dry_run, retitle=args.retitle
            )
            if args.dry_run:
                session.rollback()
            else:
                session.commit()
            logger.info(
                "%s: %s enough=%s", slug, dict(counts), enough_to_score(session, policy.id)
            )


if __name__ == "__main__":
    main()