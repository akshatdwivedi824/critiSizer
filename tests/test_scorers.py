from datetime import UTC, datetime

import httpx
import pytest
from factories import make_aspects
from sqlalchemy import func, select

from critisizer.models import EvidenceRun, Indicator, Policy, SourceItem
from critisizer.scoring import run
from critisizer.scoring.cache import CachedScorer
from critisizer.scoring.contract import ScorerError, ScoringRequest, SourceExcerpt
from critisizer.scoring.fake import FakeScorer
from critisizer.scoring.hosted import AnthropicScorer, Budget, strip_fence
from critisizer.scoring.ollama import OllamaScorer

REQUEST = ScoringRequest(
    "Agnipath Scheme",
    2022,
    [
        SourceExcerpt(
            1, "Hindustan Times", "The Agnipath scheme text.", 2, "https://x/1", "T"
        )
    ],
)


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _Post:
    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        if self.error:
            raise self.error
        return _Resp(self.data)


def test_ollama_returns_the_message_and_asks_for_json():
    http = _Post({"message": {"content": '{"a": 1}'}})
    scorer = OllamaScorer(http=http)
    assert scorer.score(REQUEST) == '{"a": 1}'
    sent = http.calls[0]["json"]
    assert sent["format"] == "json"
    assert sent["stream"] is False
    assert sent["options"]["temperature"] == 0
    assert scorer.name == "ollama:qwen2.5:7b"


def test_ollama_failure_is_a_scorer_error():
    scorer = OllamaScorer(http=_Post(error=httpx.ConnectError("down")))
    with pytest.raises(ScorerError):
        scorer.score(REQUEST)


def _hosted(tmp_path, data, max_tokens=100_000, key="k"):
    budget = Budget(tmp_path / "ledger.json", max_tokens)
    http = _Post(data)
    return AnthropicScorer(key, budget, http=http), budget, http


def test_hosted_returns_text_and_counts_tokens(tmp_path):
    data = {
        "content": [{"text": "{}"}],
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }
    scorer, budget, http = _hosted(tmp_path, data)
    assert scorer.score(REQUEST) == "{}"
    assert budget.used() == 150
    assert "x-api-key" in http.calls[0]["headers"]


def test_hosted_refuses_a_call_over_budget(tmp_path):
    data = {"content": [{"text": "{}"}], "usage": {}}
    scorer, _, http = _hosted(tmp_path, data, max_tokens=10)
    with pytest.raises(ScorerError):
        scorer.score(REQUEST)
    assert http.calls == []


def test_hosted_needs_a_key(tmp_path):
    with pytest.raises(ScorerError):
        AnthropicScorer("", Budget(tmp_path / "l.json", 10))


def test_code_fences_are_stripped():
    assert strip_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_fence('{"a": 1}') == '{"a": 1}'


class _Counting:
    name = "counting"

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def score(self, request):
        self.calls += 1
        return self.answers.pop(0)


def test_cache_answers_repeats_without_calling_the_model(tmp_path):
    inner = _Counting(['{"a": 1}'])
    scorer = CachedScorer(inner, tmp_path)
    assert scorer.score(REQUEST) == scorer.score(REQUEST)
    assert inner.calls == 1


def test_cache_never_stores_a_broken_answer(tmp_path):
    inner = _Counting(["not json", '{"a": 1}'])
    scorer = CachedScorer(inner, tmp_path)
    scorer.score(REQUEST)
    assert scorer.score(REQUEST) == '{"a": 1}'
    assert inner.calls == 2


def test_each_run_number_has_its_own_cache_slot(tmp_path):
    inner = _Counting(['{"a": 1}', '{"a": 2}'])
    first = CachedScorer(inner, tmp_path, run=0).score(REQUEST)
    second = CachedScorer(inner, tmp_path, run=1).score(REQUEST)
    assert (first, second) == ('{"a": 1}', '{"a": 2}')


def test_hand_scores_ready_needs_a_filled_file(tmp_path):
    path = tmp_path / "hand.md"
    assert run.hand_scores_ready(path) is False
    path.write_text("## Policy\n- outcome_failure: __ why\n", encoding="utf-8")
    assert run.hand_scores_ready(path) is False
    path.write_text("## Policy\n- outcome_failure: 55 why\n", encoding="utf-8")
    assert run.hand_scores_ready(path) is True


def test_real_scorers_are_refused_until_hand_scores_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "HAND_SCORES", tmp_path / "missing.md")
    with pytest.raises(ScorerError):
        run.make_scorer("ollama")
    assert run.make_scorer("fake") is not None


@pytest.fixture
def aspects(session):
    return make_aspects(session)


@pytest.fixture
def policy(session):
    row = Policy(slug="score-test", name="Agnipath Scheme", year=2022, summary="x")
    session.add(row)
    session.flush()
    return row


def _item(session, policy, run_id, n, outlet, host):
    text = (
        f"Headline {n}\nThe Agnipath scheme drew criticism over short tenures. "
        f"Reporters noted that under Agnipath most recruits leave after four "
        f"years ({n})."
    )
    session.add(
        SourceItem(
            run_id=run_id,
            policy_id=policy.id,
            url=f"https://{host}/{n}",
            outlet=outlet,
            published_at=datetime(2026, 9, n, tzinfo=UTC),
            excerpt=text,
            content_hash=f"h{n}",
        )
    )


def test_scoring_needs_enough_evidence(session, policy):
    report = run.score_policy_excerpts(session, policy, FakeScorer())
    assert report.status == "not_enough_evidence"


def test_scoring_stores_unapproved_drafts(session, policy, aspects):
    evidence_run = EvidenceRun(
        policy_id=policy.id, query_version="query_v1", query_text="q", source_api="t"
    )
    session.add(evidence_run)
    session.flush()
    sources = [
        ("Hindustan Times", "www.hindustantimes.com"),
        ("The Hindu", "www.thehindu.com"),
        ("Mint", "www.livemint.com"),
    ]
    for n, (outlet, host) in enumerate(sources, start=1):
        _item(session, policy, evidence_run.id, n, outlet, host)
    session.flush()
    report = run.score_policy_excerpts(session, policy, FakeScorer())
    assert report.status == "scored"
    drafts = session.scalar(
        select(func.count(Indicator.id)).where(
            Indicator.policy_id == policy.id, Indicator.status == "ai_draft"
        )
    )
    assert drafts == report.accepted