"""Print the review queue: pending AI drafts with their quotes, and the approved
indicators each one might duplicate. Read-only.

    python scripts/review_queue.py                 # every policy with drafts
    python scripts/review_queue.py gst-rollout-2017
"""

import sys
from difflib import SequenceMatcher

from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.models import Aspect, Evidence, Indicator, Policy

SIMILAR = 0.55


def _similarity(first: str, second: str) -> float:
    return SequenceMatcher(None, first.lower(), second.lower()).ratio()


def main(slug: str | None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    with SessionLocal() as session:
        codes = {a.id: a.code for a in session.scalars(select(Aspect))}
        query = select(Policy).order_by(Policy.slug)
        if slug:
            query = query.where(Policy.slug == slug)
        for policy in session.scalars(query):
            rows = session.scalars(
                select(Indicator)
                .where(Indicator.policy_id == policy.id)
                .order_by(Indicator.aspect_id, Indicator.id)
            ).all()
            approved = [r for r in rows if r.status == "approved"]
            drafts = [r for r in rows if r.status == "ai_draft"]
            if not drafts:
                continue
            print(f"\n=== {policy.slug}: {len(drafts)} drafts, {len(approved)} approved ===")
            for draft in drafts:
                print(
                    f"\n#{draft.id} [{codes[draft.aspect_id]}] "
                    f"score {float(draft.score):.0f}  {draft.name}"
                )
                if draft.description:
                    print(f"   why: {draft.description}")
                evidence = session.scalars(
                    select(Evidence).where(Evidence.indicator_id == draft.id)
                )
                for item in evidence:
                    quote = (item.quote or "").strip()
                    print(f'   quote: "{quote}"  [{item.source_title[:60]}]')
                same_aspect = [a for a in approved if a.aspect_id == draft.aspect_id]
                for old in same_aspect:
                    if _similarity(old.name, draft.name) >= SIMILAR:
                        print(
                            f"   LIKELY DUPLICATE of approved #{old.id} "
                            f"({float(old.score):.0f}) {old.name}"
                        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)