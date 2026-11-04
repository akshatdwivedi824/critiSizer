"""Take this week's score snapshots. Safe to run twice."""

import argparse
import logging
import sys
from datetime import date

from critisizer.db import SessionLocal
from critisizer.snapshots import take_snapshots, week_start


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Store weekly score snapshots.")
    parser.add_argument(
        "--week",
        type=date.fromisoformat,
        default=None,
        help="Monday of the week, YYYY-MM-DD (default: this week)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="overwrite snapshots that already exist for this week",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    week = args.week or week_start(date.today())
    logging.basicConfig(level=logging.WARNING)
    with SessionLocal() as session:
        try:
            report = take_snapshots(session, week, replace=args.replace)
        except ValueError as exc:
            print(f"error: {exc}")
            return 2
        session.commit()
    print(
        f"week {week}: created {report.created}, replaced {report.replaced}, "
        f"skipped {report.skipped}, failed {report.failed}"
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
