import json

import pytest
from factories import make_aspects, make_policy
from sqlalchemy import select

from critisizer.models import Aspect, EvidenceRun, Indicator, SourceItem
from critisizer.scoring.contract import (
    ASPECT_CODES,
    ScorerError,
    ScoringRequest,
    SourceExcerpt,
)
from critisizer.scoring.prompt import build_prompt
from critisizer.scoring.run import MAX_PER_ASPECT, score_policy_by_aspect

SOURCES = (
    ("https://www.thehindu.com/a1", "The Hindu"),
    ("https://indianexpress.com/a2", "The Indian Express"),
    ("https://www.ndtv.com/a3", "NDTV"),
)
# Sentences are long on purpose: the sentence splitter ignores short fragments.
BODY = (
    "Policy audit report.\n"
    "The national audit office found that the scheme overshot its approved "
    "budget by a wide margin during its first year of operation. "
    "The ministry kept the full report away from the public for more than "
    "twelve months after it had received it from the auditors. "
    "Officials in the department repeatedly denied that any delay had "
    "occurred during the rollout of the programme in the districts."
)


class ScriptedScorer:
    name = "scripted"

    def __init__(self, answers):
        self.answers = answers
        self.seen = []

    def score(self, request):
        self.seen.append(request.aspect)
        answer = self.answers[request.aspect]
        if isinstance(answer, Exception):
            raise answer
        return answer


def answer(*items):
    return json.dumps({"indicators": list(items)})


def finding(aspect="cost_waste", name="Shortfall found"):
    return {
        "aspect": aspect,
        "name": name,
        "score": 60,
        "description": "The audit found a shortfall.",
        "evidence": [{"source_id": 1, "sentence": 1}],
    }


def all_none():
    return {code: answer() for code in ASPECT_CODES}


@pytest.fixture
def policy(session):
    make_aspects(session)
    return make_policy(session, "aspect-policy")


def add_sources(session, policy):
    run = EvidenceRun(
        policy_id=policy.id,
        query_version="query_v2",
        query_text="q",
        source_api="gdelt",
    )
    session.add(run)
    session.flush()
    for number, (url, outlet) in enumerate(SOURCES, start=1):
        session.add(
            SourceItem(
                run_id=run.id,
                policy_id=policy.id,
                url=url,
                outlet=outlet,
                excerpt=f"{BODY} Item {number} was reviewed by the editors.",
                content_hash=f"hash-{number}",
            )
        )
    session.flush()


def stored_aspects(session):
    rows = session.execute(
        select(Aspect.code).join(Indicator, Indicator.aspect_id == Aspect.id)
    ).all()
    return sorted(code for (code,) in rows)


def test_every_aspect_is_asked_once_in_order(session, policy):
    add_sources(session, policy)
    scorer = ScriptedScorer(all_none())
    report = score_policy_by_aspect(session, policy, scorer)
    assert scorer.seen == list(ASPECT_CODES)
    assert report.status == "scored"
    assert [o.status for o in report.outcomes] == ["none"] * 6
    assert report.usable == 6
    assert stored_aspects(session) == []


def test_the_code_sets_the_aspect_not_the_model(session, policy):
    add_sources(session, policy)
    answers = all_none()
    answers["cost_waste"] = answer(finding(aspect="legal_challenges"))
    report = score_policy_by_aspect(session, policy, ScriptedScorer(answers))
    assert report.accepted == 1
    assert stored_aspects(session) == ["cost_waste"]


def test_drafts_from_several_aspects_are_all_kept(session, policy):
    add_sources(session, policy)
    answers = all_none()
    answers["cost_waste"] = answer(finding())
    answers["equity_impact"] = answer(finding(name="Unequal burden"))
    score_policy_by_aspect(session, policy, ScriptedScorer(answers))
    assert stored_aspects(session) == ["cost_waste", "equity_impact"]


def test_one_failed_aspect_does_not_stop_the_others(session, policy):
    add_sources(session, policy)
    answers = all_none()
    answers["transparency_gap"] = ScorerError("timeout")
    answers["cost_waste"] = answer(finding())
    report = score_policy_by_aspect(session, policy, ScriptedScorer(answers))
    by_aspect = {o.aspect: o.status for o in report.outcomes}
    assert by_aspect["transparency_gap"] == "failed"
    assert by_aspect["cost_waste"] == "accepted"
    assert report.usable == 5


def test_unreadable_answer_counts_as_failed(session, policy):
    add_sources(session, policy)
    answers = all_none()
    answers["equity_impact"] = "not json at all"
    report = score_policy_by_aspect(session, policy, ScriptedScorer(answers))
    by_aspect = {o.aspect: o.status for o in report.outcomes}
    assert by_aspect["equity_impact"] == "failed"


def test_all_aspects_failing_is_an_error_and_stores_nothing(session, policy):
    add_sources(session, policy)
    answers = {code: ScorerError("timeout") for code in ASPECT_CODES}
    with pytest.raises(ScorerError):
        score_policy_by_aspect(session, policy, ScriptedScorer(answers))
    assert session.scalars(select(Indicator)).all() == []


def test_a_looping_model_is_capped_per_aspect(session, policy):
    add_sources(session, policy)
    answers = all_none()
    answers["cost_waste"] = answer(*[finding(name=f"Shortfall {i}") for i in range(6)])
    report = score_policy_by_aspect(session, policy, ScriptedScorer(answers))
    assert report.accepted == MAX_PER_ASPECT


def test_findings_that_fail_verification_are_marked_rejected(session, policy):
    add_sources(session, policy)
    bad = finding()
    bad["evidence"] = [{"source_id": 1, "sentence": 99}]
    answers = all_none()
    answers["cost_waste"] = answer(bad)
    report = score_policy_by_aspect(session, policy, ScriptedScorer(answers))
    by_aspect = {o.aspect: o.status for o in report.outcomes}
    assert by_aspect["cost_waste"] == "rejected"
    assert report.rejected == 1
    assert stored_aspects(session) == []


def test_not_enough_evidence_never_calls_the_scorer(session, policy):
    scorer = ScriptedScorer(all_none())
    report = score_policy_by_aspect(session, policy, scorer)
    assert report.status == "not_enough_evidence"
    assert scorer.seen == []


def _request(aspect=None):
    excerpt = SourceExcerpt(
        id=1,
        outlet="Example Times",
        text=BODY,
        tier=2,
        url="https://example.com/a",
        title="t",
    )
    return ScoringRequest("Test Policy", 2024, [excerpt], aspect=aspect)


def test_aspect_prompt_asks_about_one_aspect_only():
    prompt = build_prompt(_request("cost_waste"))
    assert "cost_waste" in prompt
    assert "equity_impact" not in prompt
    assert "source 1: sentences 1 to" in prompt
    assert "source 1: none" not in prompt
    assert "(1) " in prompt


def test_prompt_without_an_aspect_is_still_the_single_pass_prompt():
    prompt = build_prompt(_request())
    assert "equity_impact" in prompt
    assert "cost_waste" in prompt


def test_unknown_aspect_is_refused():
    with pytest.raises(ValueError):
        build_prompt(_request("made_up"))