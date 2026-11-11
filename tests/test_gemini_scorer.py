import json

import httpx
import pytest

from critisizer.scoring import gemini
from critisizer.scoring.contract import ScorerError, ScoringRequest, SourceExcerpt

EXCERPT = SourceExcerpt(
    id=1,
    outlet="Example Times",
    text="The national audit office found that the scheme overshot its budget.",
    tier=2,
    url="https://example.com/a",
    title="t",
)
REQUEST = ScoringRequest("Test Policy", 2024, [EXCERPT], aspect="cost_waste")
EMPTY = '{"indicators": []}'


def reply(status=200, text=EMPTY):
    body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    request = httpx.Request("POST", "https://example.test")
    return httpx.Response(status, json=body, request=request)


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None):
        self.calls.append((url, json, headers))
        return self.responses.pop(0)


def make(tmp_path, http, cap=100, key="test-key"):
    ledger = gemini.CallLedger(tmp_path / "calls.json", cap)
    sleeps = []
    scorer = gemini.GeminiScorer(
        key, ledger, http=http, sleep=sleeps.append, clock=lambda: 0.0
    )
    return scorer, sleeps, ledger


def test_returns_the_model_text_and_keeps_the_key_out_of_the_url(tmp_path):
    http = FakeHttp(reply())
    scorer, _, _ = make(tmp_path, http)
    assert scorer.score(REQUEST) == EMPTY
    url, payload, headers = http.calls[0]
    assert "test-key" not in url
    assert headers["x-goog-api-key"] == "test-key"
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert scorer.name == f"gemini:{gemini.DEFAULT_MODEL}"


def test_a_code_fence_is_stripped(tmp_path):
    http = FakeHttp(reply(text="```json\n" + EMPTY + "\n```"))
    scorer, _, _ = make(tmp_path, http)
    assert scorer.score(REQUEST) == EMPTY


def test_calls_are_paced(tmp_path):
    http = FakeHttp(reply(), reply())
    scorer, sleeps, _ = make(tmp_path, http)
    scorer.score(REQUEST)
    assert sleeps == []
    scorer.score(REQUEST)
    assert sleeps == [gemini.MIN_INTERVAL_SECONDS]


def test_a_rate_limit_is_retried_after_waiting(tmp_path):
    http = FakeHttp(reply(status=429), reply())
    scorer, sleeps, ledger = make(tmp_path, http)
    assert scorer.score(REQUEST) == EMPTY
    assert gemini.RETRY_DELAYS[0] in sleeps
    assert ledger.used() == 2  # the failed attempt still counts


def test_a_rate_limit_that_never_clears_is_an_error(tmp_path):
    http = FakeHttp(reply(status=429), reply(status=429), reply(status=429))
    scorer, _, _ = make(tmp_path, http)
    with pytest.raises(ScorerError, match="gemini_http_429"):
        scorer.score(REQUEST)


def test_the_daily_cap_refuses_before_sending(tmp_path):
    http = FakeHttp(reply(), reply())
    scorer, _, _ = make(tmp_path, http, cap=1)
    scorer.score(REQUEST)
    with pytest.raises(ScorerError, match="daily_cap_reached"):
        scorer.score(REQUEST)
    assert len(http.calls) == 1


def test_the_count_starts_again_on_a_new_day(tmp_path):
    path = tmp_path / "calls.json"
    path.write_text(json.dumps({"date": "2000-01-01", "calls": 99}))
    assert gemini.CallLedger(path, 100).used() == 0


def test_an_unexpected_reply_shape_is_an_error(tmp_path):
    request = httpx.Request("POST", "https://example.test")
    http = FakeHttp(httpx.Response(200, json={}, request=request))
    scorer, _, _ = make(tmp_path, http)
    with pytest.raises(ScorerError, match="gemini_bad_response"):
        scorer.score(REQUEST)


def test_no_key_is_refused(tmp_path):
    with pytest.raises(ScorerError, match="no_api_key"):
        make(tmp_path, FakeHttp(), key="")


def test_the_key_is_read_from_the_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nGEMINI_API_KEY=abc123\n", encoding="utf-8")
    assert gemini.load_api_key(env) == "abc123"


def test_a_missing_env_file_gives_an_empty_key(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert gemini.load_api_key(tmp_path / "missing.env") == ""