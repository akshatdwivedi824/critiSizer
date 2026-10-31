import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text

from critisizer.db import SessionLocal
from critisizer.models import Evidence, Indicator, Policy
from critisizer.scorecard import load_active_rubric, score_policy
from critisizer.scoring.engine import ScoringError

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def main() -> int:
    with SessionLocal() as session:
        head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
        current = session.scalar(text("select version_num from alembic_version"))
        check("migrations at head", current == head, f"db={current} head={head}")

        policies = session.execute(select(Policy.id, Policy.slug)).all()
        check("at least 10 policies seeded", len(policies) >= 10, str(len(policies)))

        rubric = load_active_rubric(session)
        scores = {}
        failed = []
        for policy_id, slug in policies:
            try:
                scores[slug] = score_policy(session, policy_id, rubric)
            except ScoringError as exc:
                failed.append(f"{slug}: {exc}")
        check("every policy scores without error", not failed, "; ".join(failed))

        overall = [float(r.overall_rating) for r in scores.values()]
        if overall:
            check(
                "scores are spread (min < 25, max > 60)",
                min(overall) < 25 and max(overall) > 60,
                f"min={min(overall):.1f} max={max(overall):.1f}",
            )
        spikes = sum(1 for r in scores.values() if r.spike_flag)
        check("at least one spike flag", spikes >= 1, str(spikes))

        excluded = session.scalar(
            select(Evidence.id).where(Evidence.verification_multiplier == 0).limit(1)
        )
        check("an excluded allegation exists", excluded is not None)

        tiers = set(session.scalars(select(Evidence.source_tier).distinct()))
        check("evidence tiers 1-4 all used", tiers >= {1, 2, 3, 4}, str(sorted(tiers)))

        weighted = session.scalar(select(Indicator.id).where(Indicator.weight != 1).limit(1))
        check("a non-default indicator weight exists", weighted is not None)

    for path in [
        "docs/adr/0001-database-and-score-versioning.md",
        "docs/capacity.md",
        "LOG.md",
        "README.md",
    ]:
        check(f"file exists: {path}", Path(path).is_file())

    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failures = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - failures}/{len(results)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())