"""Read-only list of approved indicators with their quotes, for an audit.

    uv run python scripts\\audit_approved.py              older prompts only
    uv run python scripts\\audit_approved.py --all
    uv run python scripts\\audit_approved.py --slug dpdp-act-2023
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.models import Aspect, Evidence, Indicator, Policy

CURRENT_PROMPT = "prompt_v4"
QUOTE_CHARS = 230


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="include prompt_v4 too")
    parser.add_argument("--slug")
    args = parser.parse_args()

    query = (
        select(Indicator, Policy.slug, Aspect.code)
        .join(Policy, Policy.id == Indicator.policy_id)
        .join(Aspect, Aspect.id == Indicator.aspect_id)
        .where(Indicator.status == "approved")
        .order_by(Policy.slug, Aspect.code, Indicator.id)
    )
    if args.slug:
        query = query.where(Policy.slug == args.slug)

    shown = 0
    with SessionLocal() as session:
        for indicator, slug, code in session.execute(query).all():
            if not args.all and indicator.prompt_version == CURRENT_PROMPT:
                continue
            shown += 1
            print(
                f"\n#{indicator.id} {slug} [{code}] score {float(indicator.score):g}"
                f"  {indicator.model} / {indicator.prompt_version}"
            )
            print(f"   {indicator.name}")
            evidence = session.scalars(
                select(Evidence).where(Evidence.indicator_id == indicator.id)
            ).all()
            for ev in evidence:
                text = (ev.quote or "").replace("\n", " ")[:QUOTE_CHARS]
                print(f'   - "{text}"')
    print(f"\n{shown} indicators shown")


if __name__ == "__main__":
    main()