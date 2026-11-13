"""Approve or reject AI drafts through the real admin API, against the LOCAL
database only. Review happens locally; scripts/export_reviewed.py publishes it.

    python scripts/review_apply.py --approve 161 159 --reject 158 160
"""

import argparse
import sys

from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from critisizer.config import get_settings
from critisizer.main import app

BASE = "/api/admin/drafts"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def main(approve: list[int], reject: list[int]) -> None:
    overlap = set(approve) & set(reject)
    if overlap:
        sys.exit(f"ids cannot be both approved and rejected: {sorted(overlap)}")
    settings = get_settings()
    host = make_url(settings.database_url).host
    if host not in LOCAL_HOSTS:
        sys.exit(f"refusing to review on a non-local database ({host})")
    if not settings.admin_token:
        sys.exit("ADMIN_TOKEN is not set, so the admin API is disabled")

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.admin_token}"}
    failed = 0
    for action, ids in (("approve", approve), ("reject", reject)):
        for indicator_id in ids:
            response = client.post(f"{BASE}/{indicator_id}/{action}", headers=headers)
            if response.is_success:
                print(f"ok      {action} #{indicator_id}")
            else:
                failed += 1
                print(f"FAILED  {action} #{indicator_id}: {response.status_code} {response.text[:200]}")
    print(f"\n{len(approve) + len(reject) - failed} done, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve", nargs="*", type=int, default=[])
    parser.add_argument("--reject", nargs="*", type=int, default=[])
    args = parser.parse_args()
    main(args.approve, args.reject)