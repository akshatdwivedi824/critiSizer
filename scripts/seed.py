import hashlib
import sys
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.models import (
    Aspect,
    Evidence,
    Indicator,
    Policy,
    RubricVersion,
    RubricWeight,
)

DEFAULT_FILE = Path("seed/policies.yaml")


def content_hash(url: str, text: str) -> str:
    return hashlib.sha256(f"{url}\n{text}".encode()).hexdigest()


def get_or_create_aspects(session, aspects):
    by_code = {}
    for item in aspects:
        aspect = session.scalar(select(Aspect).where(Aspect.code == item["code"]))
        if aspect is None:
            aspect = Aspect(
                code=item["code"], name=item["name"], definition=item["definition"]
            )
            session.add(aspect)
            session.flush()
        by_code[item["code"]] = aspect
    return by_code


def get_or_create_rubric(session, rubric, aspects, by_code):
    version = session.scalar(
        select(RubricVersion).where(RubricVersion.label == rubric["label"])
    )
    if version is None:
        version = RubricVersion(
            label=rubric["label"], min_ratings=rubric["min_ratings"], is_active=True
        )
        session.add(version)
        session.flush()
    for item in aspects:
        aspect = by_code[item["code"]]
        existing = session.scalar(
            select(RubricWeight).where(
                RubricWeight.rubric_version_id == version.id,
                RubricWeight.aspect_id == aspect.id,
            )
        )
        if existing is None:
            session.add(
                RubricWeight(
                    rubric_version_id=version.id,
                    aspect_id=aspect.id,
                    weight=Decimal(str(item.get("weight", 1))),
                )
            )
    session.flush()
    return version


def load_policies(session, policies, by_code):
    created = 0
    for item in policies:
        if session.scalar(select(Policy).where(Policy.slug == item["slug"])):
            continue
        policy = Policy(
            slug=item["slug"],
            name=item["name"],
            year=item["year"],
            summary=item["summary"],
        )
        session.add(policy)
        session.flush()
        for ind in item["indicators"]:
            indicator = Indicator(
                policy_id=policy.id,
                aspect_id=by_code[ind["aspect"]].id,
                name=ind["name"],
                score=Decimal(str(ind["score"])),
                weight=Decimal(str(ind.get("weight", 1))),
                description=ind.get("description"),
            )
            session.add(indicator)
            session.flush()
            for ev in ind.get("evidence", []):
                session.add(
                    Evidence(
                        indicator_id=indicator.id,
                        source_url=ev["url"],
                        source_title=ev["title"],
                        source_tier=ev["tier"],
                        verification_multiplier=Decimal(str(ev["multiplier"])),
                        content_hash=content_hash(ev["url"], ev["text"]),
                    )
                )
        created += 1
    return created


def main(path: Path = DEFAULT_FILE) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    with SessionLocal() as session:
        by_code = get_or_create_aspects(session, data["aspects"])
        get_or_create_rubric(session, data["rubric"], data["aspects"], by_code)
        created = load_policies(session, data["policies"], by_code)
        session.commit()
    print(f"policies created: {created}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FILE)