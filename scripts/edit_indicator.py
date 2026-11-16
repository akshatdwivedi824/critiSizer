"""Reword the description of one approved indicator, on the LOCAL database only.
The score, name and evidence are not touched; the change is written to the audit
log and reaches the live site through scripts/export_reviewed.py.

    python scripts/edit_indicator.py --id 289 --description "A petition argued ..."
"""

import argparse
import sys

from sqlalchemy.engine import make_url

from critisizer.audit import record_audit
from critisizer.config import get_settings
from critisizer.db import SessionLocal
from critisizer.models import Indicator

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
ACTION = "indicator.edit_description"


def main(indicator_id: int, description: str) -> None:
    host = make_url(get_settings().database_url).host
    if host not in LOCAL_HOSTS:
        sys.exit(f"refusing to write to a non-local database ({host})")
    if not 10 <= len(description) <= 500:
        sys.exit("--description must be 10 to 500 characters")
    with SessionLocal() as session:
        indicator = session.get(Indicator, indicator_id)
        if indicator is None:
            sys.exit(f"no indicator #{indicator_id}")
        if indicator.status != "approved":
            sys.exit(f"#{indicator_id} is {indicator.status}, not approved")
        before = indicator.description
        indicator.description = description
        record_audit(
            session,
            ACTION,
            "indicator",
            indicator.id,
            {"before": before, "after": description, "via": "scripts/edit_indicator.py"},
        )
        session.commit()
        print(f"ok  #{indicator_id} description updated")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--description", required=True)
    args = parser.parse_args()
    main(args.id, args.description)