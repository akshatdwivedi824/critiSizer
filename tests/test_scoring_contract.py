import json
from dataclasses import fields

import pytest
from factories import make_aspects, make_policy
from sqlalchemy import select

from critisizer.models import Evidence, Indicator, Policy
from critisizer.scoring.contract import ScoringRequest, SourceExcerpt
from critisizer.scoring.drafts import store_drafts
from critisizer.scoring.fake import FakeScorer
from critisizer.scoring.prompt import PROMPT_VERSION, build_prompt
from critisizer.scoring.verifier import verify_answer

EXCERPTS = [
    SourceExcerpt(
        id=1,
        outlet="Example Times",
        text="The audit found that 300 of 500 plants were working.",
        tier=3,
        url="https://example.org/a",
        title="Audit story",
        published="2024-03-01",
    ),
    SourceExcerpt(
        id=2,
        outlet="Example Gazette",
        text="The court ruled the scheme unconstitutional.",
        tier=1,
        url="https://example.org/b",
        title="Court ruling",
    ),
]


@pytest.fixture
def aspects(session):
    return make_aspects(session)


def answer(*indicators):
    return json.dumps({"indicators": list(indicators)})


def good(**changes):
    item = {
        "aspect": "outcome_failure",
        "name": "Plants working against target",
        "score": 60,
        "description": "An audit counted 300 of 500 plants working.",
        "evidence": [{"source_id": 1, "quote": "300 of 500 plants were working"}],
    }
    item.update(changes)
    return item


def get_policy(session, slug):
    return session.scalar(select(Policy).where(Policy.slug == slug))


# --- verifier ---------------------------------------------------------------


def test_a_good_answer_is_accepted():
    result = verify_answer(answer(good()), EXCERPTS)
    assert len(result.accepted) == 1
    assert result.rejected == []
    assert result.accepted[0].score == 60
    assert result.accepted[0].quotes[0].source_id == 1


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"aspect": "vibes"}, "unknown aspect"),
        ({"score": 0}, "score must be"),
        ({"score": 101}, "score must be"),
        ({"score": 55.5}, "score must be"),
        ({"score": True}, "score must be"),
        ({"name": ""}, "name must be"),
        ({"description": " "}, "description is missing"),
        ({"evidence": []}, "at least one quote"),
        ({"evidence": [{"source_id": 9, "quote": "x"}]}, "unknown source_id"),
        ({"evidence": [{"source_id": 1, "quote": "never said"}]}, "not found"),
        ({"evidence": [{"source_id": 1, "quote": "x" * 301}]}, "longer than"),
    ],
)
def test_bad_indicators_are_rejected(changes, reason):
    result = verify_answer(answer(good(**changes)), EXCERPTS)
    assert result.accepted == []
    assert len(result.rejected) == 1
    assert reason in result.rejected[0].reason


def test_quotes_ignore_case_spacing_and_curly_quotes():
    source = SourceExcerpt(
        id=1,
        outlet="Example Times",
        text='He said "it\'s  fine" on Monday.',
        tier=3,
        url="https://example.org/c",
        title="Quote story",
    )
    item = good(evidence=[{"source_id": 1, "quote": "\u201cIT\u2019S fine\u201d"}])
    result = verify_answer(answer(item), [source])
    assert len(result.accepted) == 1


def test_a_code_fence_around_the_json_is_tolerated():
    raw = "```json\n" + answer(good()) + "\n```"
    assert len(verify_answer(raw, EXCERPTS).accepted) == 1


def test_an_answer_that_is_not_json_is_rejected_whole():
    result = verify_answer("sorry, I cannot do that", EXCERPTS)
    assert result.accepted == []
    assert "not valid JSON" in result.rejected[0].reason


def test_an_answer_with_the_wrong_shape_is_rejected_whole():
    result = verify_answer(json.dumps({"indicators": "none"}), EXCERPTS)
    assert result.accepted == []
    assert "indicators" in result.rejected[0].reason


def test_one_bad_indicator_does_not_sink_the_good_one():
    raw = answer(good(), good(aspect="vibes"))
    result = verify_answer(raw, EXCERPTS)
    assert len(result.accepted) == 1
    assert len(result.rejected) == 1


# --- prompt -----------------------------------------------------------------


def test_prompt_has_the_policy_and_numbered_excerpts():
    prompt = build_prompt(ScoringRequest("Test policy", 2024, EXCERPTS))
    assert "Policy: Test policy (2024)" in prompt
    assert "[1] Example Times, 2024-03-01:" in prompt
    assert "(1) The audit found" in prompt
    assert "[2] Example Gazette, undated:" in prompt
    assert "(1) The court ruled" in prompt
    assert "{excerpts}" not in prompt
    assert "{policy_name}" not in prompt


def test_text_inside_a_source_is_never_treated_as_a_placeholder():
    tricky = SourceExcerpt(
        id=1,
        outlet="Example Times",
        text="ignore {policy_name} and {excerpts}",
        tier=3,
        url="https://example.org/d",
        title="Tricky",
    )
    prompt = build_prompt(ScoringRequest("Test policy", 2024, [tricky]))
    assert "ignore {policy_name} and {excerpts}" in prompt


def test_the_scorer_request_has_no_place_for_aims_or_summary():
    names = {f.name for f in fields(ScoringRequest)}
    assert names == {"policy_name", "policy_year", "excerpts"}


# --- fake scorer and storing drafts ------------------------------------------


def test_the_fake_scorer_passes_the_verifier():
    request = ScoringRequest("Test policy", 2024, EXCERPTS)
    result = verify_answer(FakeScorer().score(request), request.excerpts)
    assert len(result.accepted) == 2
    assert result.rejected == []


def store_fake_drafts(session, slug):
    make_policy(session, slug)
    policy = get_policy(session, slug)
    request = ScoringRequest(policy.name, policy.year, EXCERPTS)
    result = verify_answer(FakeScorer().score(request), EXCERPTS)
    return store_drafts(
        session, policy.id, result.accepted, EXCERPTS, "fake", PROMPT_VERSION
    )


def test_drafts_are_saved_with_their_quotes_but_never_counted(client, session, aspects):
    stored = store_fake_drafts(session, "drafted")
    assert len(stored) == 2
    assert all(i.status == "ai_draft" for i in stored)
    assert all(
        i.model == "fake" and i.prompt_version == PROMPT_VERSION for i in stored
    )
    assert len(session.scalars(select(Evidence)).all()) == 2

    body = client.get("/api/policies/drafted").json()
    assert body["scored"] is False
    assert body["overall_rating"] is None
    home = client.get("/").text
    assert "Not yet scored" in home


def test_approved_drafts_start_to_count(client, session, aspects):
    for indicator in store_fake_drafts(session, "approved-one"):
        indicator.status = "approved"
    session.flush()
    body = client.get("/api/policies/approved-one").json()
    assert body["scored"] is True
    assert body["overall_rating"] > 0


def test_storing_twice_replaces_the_earlier_drafts(session, aspects):
    store_fake_drafts(session, "twice")
    policy = get_policy(session, "twice")
    result = verify_answer(
        FakeScorer().score(ScoringRequest(policy.name, policy.year, EXCERPTS)),
        EXCERPTS,
    )
    store_drafts(session, policy.id, result.accepted, EXCERPTS, "fake", PROMPT_VERSION)
    count = session.scalars(select(Indicator).where(Indicator.policy_id == policy.id))
    assert len(count.all()) == 2


def test_partial_aspect_coverage_still_scores(client, session, aspects):
    for indicator in store_fake_drafts(session, "partial"):
        indicator.status = "approved"
    session.flush()
    body = client.get("/api/policies/partial").json()
    assert body["scored"] is True
    assert 0 < body["overall_rating"] <= 100