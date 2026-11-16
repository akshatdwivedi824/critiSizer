import pytest
from factories import CODES, fill_policy, make_aspects
from sqlalchemy import select
from test_aspect_resolution import add_sources

from critisizer.models import Aspect, AspectReview, Evidence

LAST = "equity_impact"
FIVE = {code: (40, [1.0]) for code in CODES if code != LAST}
# Fewer than the four realised aspects that method v2 needs for a rating.
THREE = {code: (40, [1.0]) for code in CODES[:3]}


@pytest.fixture
def aspects(session):
    return make_aspects(session)


def mark_none_found(session, policy, aspects, reason="read all sources; none found"):
    session.add(
        AspectReview(
            policy_id=policy.id,
            aspect_id=aspects[LAST].id,
            outcome="no_negative_evidence",
            reason=reason,
        )
    )
    session.commit()


def test_partial_policy_page_renders_as_under_review(client, session, aspects):
    policy = fill_policy(session, aspects, "partial", THREE)
    add_sources(session, policy, 4, 2)
    response = client.get("/policies/partial")
    assert response.status_code == 200
    assert "Not yet rated" in response.text
    assert "needs 4 aspects" in response.text
    assert "3 so far" in response.text
    assert "Not yet rated" in response.text
    assert "Based on 4 collected sources from 2 outlets" in response.text
    assert "</span> overall" not in response.text  # the rated card's wording
    assert "Expert average" not in response.text


def test_home_shows_under_review_instead_of_a_number(client, session, aspects):
    fill_policy(session, aspects, "partial", THREE)
    session.commit()
    html = client.get("/").text
    assert "Not yet rated" in html
    assert "3 of 4 aspects" in html
    assert "SPIKE" not in html


def test_five_realised_aspects_are_rated_without_a_review(client, session, aspects):
    policy = fill_policy(session, aspects, "five", FIVE)
    add_sources(session, policy, 4, 2)
    html = client.get("/policies/five").text
    assert "Under review" not in html


def test_none_found_aspect_shows_label_and_reason(client, session, aspects):
    policy = fill_policy(session, aspects, "whole", FIVE)
    add_sources(session, policy, 4, 2)
    mark_none_found(session, policy, aspects, reason="no equity harm in any source")
    html = client.get("/policies/whole").text
    assert "No negative evidence found in the collected sources" in html
    assert "no equity harm in any source" in html
    assert "33.3" in html
    assert "Under review" not in html


def test_home_shows_the_number_once_rated(client, session, aspects):
    policy = fill_policy(session, aspects, "whole", FIVE)
    mark_none_found(session, policy, aspects)
    assert "33.3" in client.get("/").text


def test_quote_and_outlet_are_shown_and_escaped(client, session, aspects):
    fill_policy(session, aspects, "quoted", {"outcome_failure": (60, [1.0])})
    for ev in session.scalars(select(Evidence)):
        ev.quote = "The <b>audit</b> found a shortfall."
    session.commit()
    html = client.get("/policies/quoted").text
    assert "The &lt;b&gt;audit&lt;/b&gt; found a shortfall." in html
    assert "<b>audit</b>" not in html


def test_every_aspect_is_listed_on_a_policy_page(client, session, aspects):
    fill_policy(session, aspects, "partial", THREE)
    session.commit()
    html = client.get("/policies/partial").text
    for aspect in session.scalars(select(Aspect)):
        assert aspect.name in html


def test_pages_carry_the_review_note(client, session, aspects):
    fill_policy(session, aspects, "partial", THREE)
    session.commit()
    assert "AI-drafted, human-reviewed" in client.get("/").text
    assert "AI-drafted, human-reviewed" in client.get("/policies/partial").text