from datetime import date

import pytest
from factories import fill_policy, make_aspects
from sqlalchemy import select

from critisizer.models import AspectReview, Indicator
from critisizer.reviewed_data import COUNTED, export_reviewed, import_reviewed


@pytest.fixture
def aspects(session):
    return make_aspects(session)


def test_format_2_carries_the_new_fields_and_restores_them(session, aspects):
    policy = fill_policy(session, aspects, "p", {"outcome_failure": (60, [1.0])})
    indicator = session.scalars(
        select(Indicator).where(Indicator.policy_id == policy.id)
    ).one()
    indicator.evidence_status = "projected"
    indicator.projection_source = "PRS estimate"
    session.add(
        AspectReview(
            policy_id=policy.id,
            aspect_id=aspects["cost_waste"].id,
            outcome="too_early",
            reason="not in force until 2027",
            review_date=date(2027, 1, 1),
        )
    )
    session.commit()

    data = export_reviewed(session, ["p"])
    entry = data["policies"][0]
    assert data["format"] == 2
    assert entry["indicators"][0]["evidence_status"] == "projected"
    assert entry["indicators"][0]["projection_source"] == "PRS estimate"
    assert entry["aspect_reviews"][0]["review_date"] == "2027-01-01"

    # Lose the v2 state, then let the import put it back.
    indicator.evidence_status = "realised"
    indicator.projection_source = None
    for review in session.scalars(select(AspectReview)).all():
        session.delete(review)
    session.commit()

    import_reviewed(session, data)
    session.commit()
    session.refresh(indicator)
    assert indicator.evidence_status == "projected"
    assert indicator.projection_source == "PRS estimate"
    review = session.scalars(select(AspectReview)).one()
    assert review.outcome == "too_early"
    assert review.review_date == date(2027, 1, 1)


def test_format_1_files_still_import_and_unknown_formats_do_not(session, aspects):
    assert import_reviewed(session, {"format": 1, "policies": []}) == dict.fromkeys(
        COUNTED, 0
    )
    with pytest.raises(ValueError):
        import_reviewed(session, {"format": 99, "policies": []})