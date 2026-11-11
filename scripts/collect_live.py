"""Live evidence collection from GDELT, for all policies or the ones named.

--dry-run only asks GDELT what it would return and prints the yield per outlet.
It fetches no pages and writes nothing.
"""

import argparse
import logging
from collections import Counter

from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.evidence.collect import collect_for_policy, enough_to_score
from critisizer.evidence.gdelt import CollectError, GdeltClient
from critisizer.evidence.outlets import outlet_for
from critisizer.evidence.query import build_query, search_phrases
from critisizer.models import Policy

logger = logging.getLogger("collect_live")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", action="append", help="repeat for several")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    client = GdeltClient()
    with SessionLocal() as session:
        query = select(Policy).order_by(Policy.id)
        if args.slug:
            query = query.where(Policy.slug.in_(args.slug))
        for policy in session.scalars(query).all():
            try:
                if args.dry_run:
                    phrases = search_phrases(policy.name, policy.slug)
                    _, articles = client.search(build_query(phrases))
                    by_outlet = Counter(
                        o.name for a in articles if (o := outlet_for(a.domain))
                    )
                    logger.info(
                        "%-30s GDELT returned %d, from allowed outlets %d: %s",
                        policy.slug, len(articles), sum(by_outlet.values()),
                        dict(by_outlet),
                    )
                    continue
                report = collect_for_policy(session, policy, client)
                session.commit()
                logger.info(
                    "%-30s found %d stored %d skipped %s enough=%s",
                    policy.slug, report.found, report.stored, dict(report.skipped),
                    enough_to_score(session, policy.id),
                )
            except CollectError as exc:
                session.rollback()
                logger.warning("%-30s failed: %s", policy.slug, exc)


if __name__ == "__main__":
    main()