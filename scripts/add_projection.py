"""Record a reviewer-authored PROJECTED indicator against the LOCAL database.

A projection is a named source's forward-looking statement about an aspect that
has no realised evidence yet. The reviewer picks the score; the model never
writes one. The quote must appear in a source already collected for the policy
(add_sources.py), so a projection cannot rest on invented text. It is shown with
a star, drawn as a dashed marker, and is never part of the overall rating.

    python scripts/add_projection.py --slug electoral-bonds-scheme-2018 \
        --aspect ground_level_harm --score 40 \
        --name "Risk of donor-party quid pro quo" \
        --description "One sentence on what the source expects." \
        --basis "the Supreme Court's February 2024 ruling, as reported by Scroll" \
        --url https://scroll.in/... --quote "text copied from the article"

Publish afterwards with scripts/export_reviewed.py, as for any approved change.
"""

import argparse
import hashlib
import re
import sys
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.engine import make_url

from critisizer.audit import record_audit
from critisizer.config import get_settings
from critisizer.db import SessionLocal
from critisizer.evidence.outlets import outlet_for
from critisizer.models import Aspect, Evidence, Indicator, Policy, SourceItem

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
ACTION = "indicator.projection_add"


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main(args: argparse.Namespace) -> None:
    host = make_url(get_settings().database_url).host
    if host not in LOCAL_HOSTS:
        sys.exit(f"refusing to write to a non-local database ({host})")
    if not 0 <= args.score <= 100:
        sys.exit("--score must be between 0 and 100")
    if len(args.basis) < 10:
        sys.exit("--basis must name the source and its forecast (10+ characters)")
    quote = _squash(args.quote)
    if len(quote) < 20:
        sys.exit("--quote must be at least 20 characters, copied from the source")

    with SessionLocal() as session:
        policy = session.scalar(select(Policy).where(Policy.slug == args.slug))
        if policy is None:
            sys.exit(f"no such policy: {args.slug}")
        aspect = session.scalar(select(Aspect).where(Aspect.code == args.aspect))
        if aspect is None:
            sys.exit(f"no such aspect: {args.aspect}")

        scored = session.scalar(
            select(Indicator.id).where(
                Indicator.policy_id == policy.id,
                Indicator.aspect_id == aspect.id,
                Indicator.status == "approved",
            )
        )
        if scored is not None:
            sys.exit(
                f"{args.aspect} already has an approved indicator (#{scored}); "
                "a projection is only for an aspect with no evidence yet"
            )

        item = session.scalar(
            select(SourceItem).where(
                SourceItem.policy_id == policy.id, SourceItem.url == args.url
            )
        )
        if item is None:
            sys.exit("that URL is not a collected source for this policy")
        if quote not in _squash(item.excerpt):
            sys.exit("the quote does not appear in the stored excerpt of that source")
        outlet = outlet_for(urlparse(item.url).netloc)
        if outlet is None:
            sys.exit("the outlet is not on the allow-list")

        indicator = Indicator(
            policy_id=policy.id,
            aspect_id=aspect.id,
            name=args.name,
            score=args.score,
            weight=1,
            description=args.description,
            status="approved",
            model="reviewer",
            prompt_version=None,
            evidence_status="projected",
            projection_source=args.basis,
        )
        session.add(indicator)
        session.flush()
        session.add(
            Evidence(
                indicator_id=indicator.id,
                source_url=item.url,
                source_title=item.excerpt.split("\n", 1)[0][:300],
                source_tier=outlet.tier,
                verification_multiplier=1,
                content_hash=hashlib.sha256(
                    f"{item.url}\n{quote}".encode()
                ).hexdigest(),
                quote=quote,
                source_item_id=item.id,
            )
        )
        record_audit(
            session,
            ACTION,
            "indicator",
            indicator.id,
            {
                "policy": args.slug,
                "aspect": args.aspect,
                "score": args.score,
                "basis": args.basis,
                "via": "scripts/add_projection.py",
            },
        )
        session.commit()
        print(f"ok  projected indicator #{indicator.id} on {args.aspect} ({args.score})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--aspect", required=True)
    parser.add_argument("--score", type=float, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--basis", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--quote", required=True)
    main(parser.parse_args())