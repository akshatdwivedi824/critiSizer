"""List sentences in a policy's collected sources that contain any of the given
terms, with the source URL. Read-only; use it to pick quotes for review or for
scripts/add_projection.py.

    python scripts/find_quotes.py --slug dpdp-act-2023 --terms cost compliance burden
"""

import argparse
import re

from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.models import Policy, SourceItem


def main(slug: str, terms: list[str], limit: int) -> None:
    wanted = [t.lower() for t in terms]
    with SessionLocal() as session:
        policy = session.scalar(select(Policy).where(Policy.slug == slug))
        if policy is None:
            raise SystemExit(f"no such policy: {slug}")
        items = session.scalars(
            select(SourceItem)
            .where(SourceItem.policy_id == policy.id)
            .order_by(SourceItem.id)
        ).all()
        shown = 0
        for item in items:
            text = re.sub(r"\s+", " ", item.excerpt)
            hits = [
                s.strip()
                for s in re.split(r"(?<=[.!?])\s+", text)
                if any(t in s.lower() for t in wanted)
            ]
            if not hits:
                continue
            print(f"\n{item.url}")
            for sentence in hits[:3]:
                print(f"   - {sentence}")
                shown += 1
            if shown >= limit:
                break
        print(f"\n{len(items)} sources searched, {shown} sentences shown")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--terms", nargs="+", required=True)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    main(args.slug, args.terms, args.limit)