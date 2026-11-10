from decimal import Decimal

import pytest
from factories import add_indicator, make_aspects, make_policy
from sqlalchemy import update

from critisizer.models import Evidence

GOOD = [Decimal("1.00")]


@pytest.fixture
def aspects(session):
    return make_aspects(session)


def test_unscored_policy_says_nothing_is_reviewed(client, session, aspects):
    make_policy(session, "bare-policy")
    session.commit()
    body = client.get("/api/policies/bare-policy").json()
    assert body["scored"] is False
    assert body["aspects_reviewed"] == 0
    assert body["aspects_total"] == len(aspects)
    assert body["review_note"] == "AI-drafted, human-reviewed"


def test_approved_indicator_shows_its_quote_and_provenance(client, session, aspects):
    policy = make_policy(session, "quoted-policy")
    add_indicator(session, policy, aspects["outcome_failure"], 60, GOOD)
    session.execute(update(Evidence).values(quote="The audit found a shortfall."))
    session.commit()

    body = client.get("/api/policies/quoted-policy").json()
    assert body["scored"] is True
    assert body["aspects_reviewed"] == 1
    assert body["aspects_total"] == len(aspects)
    shown = [a for a in body["aspects"] if a["indicators"]]
    assert len(shown) == 1
    evidence = shown[0]["indicators"][0]["evidence"][0]
    assert evidence["quote"] == "The audit found a shortfall."
    assert evidence["excluded"] is False


def test_unreviewed_drafts_never_appear(client, session, aspects):
    from critisizer.models import Indicator

    policy = make_policy(session, "draft-policy")
    add_indicator(session, policy, aspects["outcome_failure"], 60, GOOD)
    add_indicator(session, policy, aspects["cost_waste"], 90, GOOD)
    last = session.query(Indicator).order_by(Indicator.id.desc()).first()
    last.status = "ai_draft"
    session.commit()

    body = client.get("/api/policies/draft-policy").json()
    names = [i["name"] for a in body["aspects"] for i in a["indicators"]]
    assert len(names) == 1
    assert body["aspects_reviewed"] == 1