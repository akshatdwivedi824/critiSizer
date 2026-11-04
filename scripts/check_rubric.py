from decimal import Decimal

from sqlalchemy import func, select

from critisizer.db import SessionLocal
from critisizer.models import Aspect, RubricVersion, RubricWeight

with SessionLocal() as session:
    aspects = [
        Aspect(code=f"a{i}", name=f"Aspect {i}", definition="test") for i in range(1, 7)
    ]
    version = RubricVersion(label="test-v1")
    session.add_all([*aspects, version])
    session.flush()

    session.add_all(
        RubricWeight(
            rubric_version_id=version.id, aspect_id=a.id, weight=Decimal("1.00")
        )
        for a in aspects
    )
    session.flush()

    count = session.scalar(
        select(func.count())
        .select_from(RubricWeight)
        .where(RubricWeight.rubric_version_id == version.id)
    )
    print(count)
    session.rollback()
