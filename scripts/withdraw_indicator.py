"""Withdraw approved indicators that fail the evidence standard, LOCAL database
only. The indicator goes back to 'rejected' and the withdrawal is written to the
audit log. scripts/export_reviewed.py then carries it in each policy's
`withdrawn` list, so the live database rejects it too on the next deploy.

    python scripts/withdraw_indicator.py --ids 110 115 112 \
        --reason "claim or forecast, not realised evidence"

The reason (5-500 characters) is kept in the audit log and the export.
"""

import argparse
import sys

from sqlalchemy.engine import make_url

from critisizer.audit import record_audit
from critisizer.config import get_settings
from critisizer.db import SessionLocal
from critisizer.models import Aspect, Indicator, Policy
from critisizer.reviewed_data import WITHDRAW_ACTION

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def main(ids: list[int], reason: str) -> None:
    if not 5 <= len(reason) <= 500:
        sys.exit("--reason must be 5 to 500 characters")
    host = make_url(get_settings().database_url).host
    if host not in LOCAL_HOSTS:
        sys.exit(f"refusing to withdraw on a non-local database ({host})")

    failed = 0
    with SessionLocal() as session:
        for indicator_id in ids:
            indicator = session.get(Indicator, indicator_id)
            if indicator is None:
                failed += 1
                print(f"FAILED  #{indicator_id}: no such indicator")
                continue
            if indicator.status != "approved":
                failed += 1
                print(f"FAILED  #{indicator_id}: status is {indicator.status}")
                continue
            policy = session.get(Policy, indicator.policy_id)
            aspect = session.get(Aspect, indicator.aspect_id)
            indicator.status = "rejected"
            record_audit(
                session,
                WITHDRAW_ACTION,
                "indicator",
                indicator.id,
                {
                    "policy": policy.slug,
                    "aspect": aspect.code,
                    "name": indicator.name,
                    "reason": reason,
                    "via": "withdraw_indicator",
                },
            )
            print(f"ok      withdrew #{indicator_id} {policy.slug} {aspect.code}")
        session.commit()
    print(f"\n{len(ids) - failed} done, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="+", type=int, required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    main(args.ids, args.reason)