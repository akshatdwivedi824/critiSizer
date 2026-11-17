"""Record a reviewer-authored indicator on an aspect the model never drafted
correctly, on the LOCAL database only.

Use it as a last resort, when the stored sources clearly contain the evidence but
the drafting model keeps picking something else. The reviewer writes the name,
description and score. The quote must appear in a source already collected for
the policy, and the outlet must be on the allow-list, so the indicator cannot
rest on invented text. The row is labelled model="reviewer" and the action is
written to the audit log. Only for an aspect with no approved indicator yet.

    python scripts/add_indicator.py --slug farm-laws-2020 \
        --aspect transparency_gap --status realised --score 70 \
        --name "Bills passed by voice vote without a division" \
        --description "One sentence on what the source reports." \
        --url https://thewire.in/... --quote "text copied from the article"

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
ACTION = "indicator.reviewer_add"


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main(args: argparse.Namespace) -> None:
    host = make_url(get_settings().database_url).host
    if host not in LOCAL_HOSTS:
        sys.exit(f"refusing to write to a non-local database ({host})")
    if not 0 <= args.score <= 100:
        sys.exit("--score must be between 0 and 100")
    if not 10 <= len(args.description) <= 500:
        sys.exit("--description must be 10 to 500 characters")
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

        existing = session.scalar(
            select(Indicator.id).where(
                Indicator.policy_id == policy.id,
                Indicator.aspect_id == aspect.id,
                Indicator.status == "approved",
                Indicator.model != "reviewer",
            )
        )
        if existing is not None:
            sys.exit(
                f"{args.aspect} already has an approved model-drafted indicator "
                f"(#{existing}); this script only fills an empty aspect"
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
            evidence_status=args.status,
            projection_source=None,
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
                "status": args.status,
                "via": "scripts/add_indicator.py",
            },
        )
        session.commit()
        print(f"ok  indicator #{indicator.id} on {args.aspect} ({args.score}, {args.status})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--aspect", required=True)
    parser.add_argument("--status", choices=["realised", "alleged"], required=True)
    parser.add_argument("--score", type=float, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--quote", required=True)
    main(parser.parse_args())