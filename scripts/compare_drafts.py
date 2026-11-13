"""Compare one model's drafts with the approved indicators.

    python scripts/compare_drafts.py                      # list models and counts
    python scripts/compare_drafts.py gemini:gemini-3.5-flash-lite
"""

import sys
from collections import Counter

from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.models import Aspect, Indicator, Policy


def main(model: str | None) -> None:
    with SessionLocal() as session:
        if model is None:
            counts = Counter(
                (row.model, row.status)
                for row in session.scalars(select(Indicator))
            )
            for (name, status), total in sorted(counts.items(), key=str):
                print(f"{name!s:45} {status:9} {total}")
            return
        codes = {a.id: a.code for a in session.scalars(select(Aspect))}
        for policy in session.scalars(select(Policy).order_by(Policy.slug)):
            rows = session.scalars(
                select(Indicator).where(Indicator.policy_id == policy.id)
            ).all()
            approved = [r for r in rows if r.status == "approved"]
            drafts = [r for r in rows if r.status == "ai_draft" and r.model == model]
            print(f"\n{policy.slug}: approved={len(approved)} drafts={len(drafts)}")
            for code in sorted(set(codes.values())):
                old = [r for r in approved if codes[r.aspect_id] == code]
                new = [r for r in drafts if codes[r.aspect_id] == code]
                if not old and not new:
                    continue
                print(f"  {code}")
                for row in old:
                    print(f"    approved {float(row.score):6.1f}  {row.name}")
                for row in new:
                    print(f"    draft    {float(row.score):6.1f}  {row.name}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)