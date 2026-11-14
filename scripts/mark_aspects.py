"""Record a reviewer's finding on an aspect, through the real admin API, against
the LOCAL database only. Publish with scripts/export_reviewed.py afterwards.

    python scripts/mark_aspects.py --slug dpdp-act-2023 --too-early cost_waste \
        --reason "Rules notified Nov 2025; phased in over 18 months" \
        --review-date 2027-06-01

    python scripts/mark_aspects.py --slug farm-laws-2020 \
        --no-negative cost_waste --reason "Laws stayed Jan 2021, repealed Nov 2021"

    python scripts/mark_aspects.py --slug dpdp-act-2023 --reopen cost_waste

Several aspect codes can follow one flag; the same reason (and date) applies to
all of them. A reason is 5 to 500 characters and goes into the audit log.
Marking an aspect that has an approved or pending indicator is refused (409).
"""

import argparse
import sys
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from critisizer.config import get_settings
from critisizer.main import app

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def main(
    slug: str,
    too_early: list[str],
    no_negative: list[str],
    reopen: list[str],
    reason: str | None,
    review_date: str | None,
) -> None:
    if (too_early or no_negative) and not (reason and 5 <= len(reason) <= 500):
        sys.exit("--reason (5 to 500 characters) is required to mark an aspect")
    if too_early:
        if not review_date:
            sys.exit("--review-date YYYY-MM-DD is required with --too-early")
        try:
            when = date.fromisoformat(review_date)
        except ValueError:
            sys.exit("--review-date must look like 2027-06-01")
        if when <= date.today():
            sys.exit("--review-date must be in the future")
    codes = too_early + no_negative + reopen
    if len(set(codes)) != len(codes):
        sys.exit("an aspect can appear only once per run")

    settings = get_settings()
    host = make_url(settings.database_url).host
    if host not in LOCAL_HOSTS:
        sys.exit(f"refusing to mark aspects on a non-local database ({host})")
    if not settings.admin_token:
        sys.exit("ADMIN_TOKEN is not set, so the admin API is disabled")

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.admin_token}"}
    base = f"/api/admin/policies/{slug}/aspects"
    failed = 0
    jobs = [
        ("too-early", "post", too_early, {"reason": reason, "review_date": review_date}),
        ("no-negative-evidence", "post", no_negative, {"reason": reason}),
        ("no-negative-evidence", "delete", reopen, None),
    ]
    for path, method, aspect_codes, body in jobs:
        for code in aspect_codes:
            url = f"{base}/{code}/{path}"
            if method == "post":
                response = client.post(url, headers=headers, json=body)
            else:
                response = client.delete(url, headers=headers)
            label = "reopen" if method == "delete" else path
            if response.is_success:
                print(f"ok      {label} {slug} {code}")
            else:
                failed += 1
                print(
                    f"FAILED  {label} {slug} {code}: "
                    f"{response.status_code} {response.text[:200]}"
                )
    done = len(codes) - failed
    print(f"\n{done} done, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--too-early", nargs="*", default=[])
    parser.add_argument("--no-negative", nargs="*", default=[])
    parser.add_argument("--reopen", nargs="*", default=[])
    parser.add_argument("--reason")
    parser.add_argument("--review-date")
    args = parser.parse_args()
    main(
        args.slug,
        args.too_early,
        args.no_negative,
        args.reopen,
        args.reason,
        args.review_date,
    )