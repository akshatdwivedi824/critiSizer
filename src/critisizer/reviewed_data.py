"""Export and import of reviewed data.

The maintainer's local database is the source of truth: collection, AI drafting
and human review all happen there. `export_reviewed` turns the reviewed part of
it into a plain dict (written to seed/reviewed.yaml by scripts/export_reviewed.py)
and `import_reviewed` loads that dict into any database, safely repeatable.

Exported: policy text, approved indicators with their evidence, approved aims,
aspect reviews, and the collected source excerpts.
Never exported: AI drafts, rejected rows, users, ratings, jobs, the audit log,
raw evidence runs and snapshots.

Import only creates or updates; it never deletes. Something rejected locally
must also be rejected on a live database, or it disappears at the next re-seed
into a fresh database.

Format 2 (method v2) adds an indicator's evidence_status and projection_source
and an aspect review's review_date. Format 1 files still import: the missing
fields default to "realised", no projection source and no review date.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from critisizer.models import (
    Aspect,
    AspectReview,
    Evidence,
    EvidenceRun,
    Indicator,
    Policy,
    PolicyAim,
    SourceItem,
)

FORMAT_VERSION = 2
SUPPORTED_FORMATS = frozenset({1, 2})
IMPORT_API = "seed"
COUNTED = ("source_items", "indicators", "evidence", "aims", "reviews")
MAX_EXCERPT_CHARS = 500


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _day(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


# ---------------------------------------------------------------- export


def export_reviewed(
    session: Session, slugs: list[str] | None = None
) -> dict[str, Any]:
    aspect_code = {row.id: row.code for row in session.scalars(select(Aspect))}
    query = select(Policy).order_by(Policy.slug)
    if slugs is not None:
        query = query.where(Policy.slug.in_(slugs))
    policies = [
        _export_policy(session, policy, aspect_code)
        for policy in session.scalars(query)
    ]
    return {"format": FORMAT_VERSION, "policies": policies}


def _export_policy(
    session: Session, policy: Policy, aspect_code: dict[int, str]
) -> dict[str, Any]:
    items = session.scalars(
        select(SourceItem)
        .where(SourceItem.policy_id == policy.id)
        .order_by(SourceItem.content_hash)
    ).all()
    item_hash = {item.id: item.content_hash for item in items}

    indicator_rows = session.scalars(
        select(Indicator).where(
            Indicator.policy_id == policy.id, Indicator.status == "approved"
        )
    ).all()
    indicator_rows.sort(key=lambda row: (aspect_code[row.aspect_id], row.name))

    indicators = []
    for row in indicator_rows:
        evidence_rows = session.scalars(
            select(Evidence)
            .where(Evidence.indicator_id == row.id)
            .order_by(Evidence.content_hash)
        ).all()
        indicators.append(
            {
                "aspect": aspect_code[row.aspect_id],
                "name": row.name,
                "score": float(row.score),
                "weight": float(row.weight),
                "description": row.description,
                "model": row.model,
                "prompt_version": row.prompt_version,
                "evidence_status": row.evidence_status,
                "projection_source": row.projection_source,
                "evidence": [
                    {
                        "url": ev.source_url,
                        "title": ev.source_title,
                        "tier": ev.source_tier,
                        "multiplier": float(ev.verification_multiplier),
                        "content_hash": ev.content_hash,
                        "archived_location": ev.archived_location,
                        "quote": ev.quote,
                        "source_item": item_hash.get(ev.source_item_id),
                    }
                    for ev in evidence_rows
                ],
            }
        )

    aims = session.scalars(
        select(PolicyAim)
        .where(PolicyAim.policy_id == policy.id, PolicyAim.status == "approved")
        .order_by(PolicyAim.position, PolicyAim.text)
    ).all()
    reviews = session.scalars(
        select(AspectReview).where(AspectReview.policy_id == policy.id)
    ).all()
    reviews.sort(key=lambda row: aspect_code[row.aspect_id])

    return {
        "slug": policy.slug,
        "name": policy.name,
        "year": policy.year,
        "summary": policy.summary,
        "summary_source_url": policy.summary_source_url,
        "aims": [
            {"text": a.text, "source_url": a.source_url, "position": a.position}
            for a in aims
        ],
        "source_items": [
            {
                "url": item.url,
                "outlet": item.outlet,
                "published_at": _iso(item.published_at),
                "excerpt": item.excerpt[:MAX_EXCERPT_CHARS],
                "content_hash": item.content_hash,
            }
            for item in items
        ],
        "indicators": indicators,
        "aspect_reviews": [
            {
                "aspect": aspect_code[r.aspect_id],
                "outcome": r.outcome,
                "reason": r.reason,
                "review_date": r.review_date.isoformat() if r.review_date else None,
            }
            for r in reviews
        ],
    }


# ---------------------------------------------------------------- import


def import_reviewed(session: Session, data: dict[str, Any]) -> dict[str, int]:
    """Load exported data. Returns how many rows of each kind were created.

    Does not commit; the caller does. Raises ValueError if the data names a
    policy or aspect the database does not have, so a mismatch fails loudly.
    """
    if data.get("format") not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported reviewed-data format: {data.get('format')}")
    aspects = {row.code: row for row in session.scalars(select(Aspect))}
    created = dict.fromkeys(COUNTED, 0)

    for entry in data.get("policies", []):
        policy = session.scalar(select(Policy).where(Policy.slug == entry["slug"]))
        if policy is None:
            raise ValueError(f"unknown policy in reviewed data: {entry['slug']}")
        for field in ("name", "year", "summary", "summary_source_url"):
            if field in entry:
                setattr(policy, field, entry[field])
        items = _import_source_items(
            session, policy, entry.get("source_items", []), created
        )
        _import_indicators(
            session, policy, aspects, items, entry.get("indicators", []), created
        )
        _import_aims(session, policy, entry.get("aims", []), created)
        _import_reviews(
            session, policy, aspects, entry.get("aspect_reviews", []), created
        )
    session.flush()
    return created


def _aspect(aspects: dict[str, Aspect], code: str) -> Aspect:
    if code not in aspects:
        raise ValueError(f"unknown aspect in reviewed data: {code}")
    return aspects[code]


def _import_run(session: Session, policy: Policy, count: int) -> EvidenceRun:
    run = session.scalars(
        select(EvidenceRun).where(
            EvidenceRun.policy_id == policy.id, EvidenceRun.source_api == IMPORT_API
        )
    ).first()
    if run is None:
        run = EvidenceRun(
            policy_id=policy.id,
            query_version="import",
            query_text="seed/reviewed.yaml",
            source_api=IMPORT_API,
            result_count=count,
        )
        session.add(run)
        session.flush()
    return run


def _import_source_items(
    session: Session,
    policy: Policy,
    entries: list[dict[str, Any]],
    created: dict[str, int],
) -> dict[str, SourceItem]:
    existing = {
        row.content_hash: row
        for row in session.scalars(
            select(SourceItem).where(SourceItem.policy_id == policy.id)
        )
    }
    run = None
    for entry in entries:
        row = existing.get(entry["content_hash"])
        if row is None:
            run = run or _import_run(session, policy, len(entries))
            row = SourceItem(
                run_id=run.id,
                policy_id=policy.id,
                content_hash=entry["content_hash"],
                url="",
                outlet="",
                excerpt="",
            )
            session.add(row)
            existing[entry["content_hash"]] = row
            created["source_items"] += 1
        row.url = entry["url"]
        row.outlet = entry["outlet"]
        row.published_at = _when(entry.get("published_at"))
        if not row.excerpt.startswith(entry["excerpt"]):
            row.excerpt = entry["excerpt"]
    session.flush()
    return existing


def _import_indicators(
    session: Session,
    policy: Policy,
    aspects: dict[str, Aspect],
    items: dict[str, SourceItem],
    entries: list[dict[str, Any]],
    created: dict[str, int],
) -> None:
    for entry in entries:
        aspect = _aspect(aspects, entry["aspect"])
        row = session.scalars(
            select(Indicator).where(
                Indicator.policy_id == policy.id,
                Indicator.aspect_id == aspect.id,
                Indicator.name == entry["name"],
            )
        ).first()
        if row is None:
            row = Indicator(
                policy_id=policy.id,
                aspect_id=aspect.id,
                name=entry["name"],
                score=_dec(entry["score"]),
            )
            session.add(row)
            created["indicators"] += 1
        row.score = _dec(entry["score"])
        row.weight = _dec(entry.get("weight", 1))
        row.description = entry.get("description")
        row.status = "approved"
        row.model = entry.get("model")
        row.prompt_version = entry.get("prompt_version")
        # Format 1 files lack these two: realised, with no projection source.
        row.evidence_status = entry.get("evidence_status") or "realised"
        row.projection_source = entry.get("projection_source")
        session.flush()
        _import_evidence(session, row, items, entry.get("evidence", []), created)


def _import_evidence(
    session: Session,
    indicator: Indicator,
    items: dict[str, SourceItem],
    entries: list[dict[str, Any]],
    created: dict[str, int],
) -> None:
    existing = {
        row.content_hash: row
        for row in session.scalars(
            select(Evidence).where(Evidence.indicator_id == indicator.id)
        )
    }
    for entry in entries:
        row = existing.get(entry["content_hash"])
        if row is None:
            row = Evidence(
                indicator_id=indicator.id,
                content_hash=entry["content_hash"],
                source_url="",
                source_title="",
                source_tier=entry["tier"],
                verification_multiplier=_dec(entry["multiplier"]),
            )
            session.add(row)
            existing[entry["content_hash"]] = row
            created["evidence"] += 1
        linked = items.get(entry.get("source_item") or "")
        row.source_url = entry["url"]
        row.source_title = entry["title"]
        row.source_tier = entry["tier"]
        row.verification_multiplier = _dec(entry["multiplier"])
        row.archived_location = entry.get("archived_location")
        row.quote = entry.get("quote")
        row.source_item_id = linked.id if linked else None
    session.flush()


def _import_aims(
    session: Session,
    policy: Policy,
    entries: list[dict[str, Any]],
    created: dict[str, int],
) -> None:
    existing = {
        row.text: row
        for row in session.scalars(
            select(PolicyAim).where(PolicyAim.policy_id == policy.id)
        )
    }
    for entry in entries:
        row = existing.get(entry["text"])
        if row is None:
            row = PolicyAim(policy_id=policy.id, text=entry["text"], source_url="")
            session.add(row)
            existing[entry["text"]] = row
            created["aims"] += 1
        row.source_url = entry["source_url"]
        row.position = entry.get("position", 0)
        row.status = "approved"


def _import_reviews(
    session: Session,
    policy: Policy,
    aspects: dict[str, Aspect],
    entries: list[dict[str, Any]],
    created: dict[str, int],
) -> None:
    for entry in entries:
        aspect = _aspect(aspects, entry["aspect"])
        row = session.scalar(
            select(AspectReview).where(
                AspectReview.policy_id == policy.id,
                AspectReview.aspect_id == aspect.id,
            )
        )
        if row is None:
            row = AspectReview(
                policy_id=policy.id,
                aspect_id=aspect.id,
                outcome=entry["outcome"],
                reason=entry["reason"],
            )
            session.add(row)
            created["reviews"] += 1
        row.outcome = entry["outcome"]
        row.reason = entry["reason"]
        row.review_date = _day(entry.get("review_date"))