"""Hosted model (Google Gemini API, free tier) with pacing and a daily call cap."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from critisizer.scoring.contract import ScorerError, ScoringRequest
from critisizer.scoring.hosted import strip_fence
from critisizer.scoring.prompt import build_prompt

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
# Check the current model names in Google AI Studio and pass --model if this
# one is not available to you.
DEFAULT_MODEL = "gemini-3.8-flash"
CALL_LEDGER = Path(".cache") / "scoring" / "gemini_calls.json"
# Conservative defaults until the real free-tier limits are read from AI Studio.
DEFAULT_DAILY_CAP = 100
MIN_INTERVAL_SECONDS = 13.0
RETRY_DELAYS = (20.0, 60.0)
RETRYABLE = {429, 500, 503}


class CallLedger:
    """Counts HTTP calls per day and refuses calls past the cap."""

    def __init__(self, path: Path, cap: int) -> None:
        self._path = Path(path)
        self._cap = cap

    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).date().isoformat()

    def used(self) -> int:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if data["date"] == self._today():
                return int(data["calls"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return 0

    def check(self) -> None:
        if self.used() >= self._cap:
            raise ScorerError("daily_cap_reached")

    def add(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"date": self._today(), "calls": self.used() + 1}
        self._path.write_text(json.dumps(data), encoding="utf-8")


def load_api_key(env_path: Path = Path(".env")) -> str:
    """The key comes from the environment or from .env. It is never printed."""
    value = os.environ.get("GEMINI_API_KEY", "")
    if value:
        return value
    try:
        lines = Path(env_path).read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ""
    for line in lines:
        name, _, raw = line.partition("=")
        if name.strip() == "GEMINI_API_KEY":
            return raw.strip().strip('"').strip("'")
    return ""


class GeminiScorer:
    def __init__(
        self,
        api_key: str,
        ledger: CallLedger,
        model: str = DEFAULT_MODEL,
        http: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        max_output: int = 4000,
    ) -> None:
        if not api_key:
            raise ScorerError("no_api_key")
        self.name = f"gemini:{model}"
        self._key = api_key
        self._ledger = ledger
        self._model = model
        self._sleep = sleep
        self._clock = clock
        self._max_output = max_output
        self._http = http or httpx.Client(timeout=120.0)
        self._last_call: float | None = None

    def _pace(self) -> None:
        if self._last_call is not None:
            wait = MIN_INTERVAL_SECONDS - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def _post(self, url: str, payload: dict, headers: dict) -> httpx.Response:
        for attempt, delay in enumerate((0.0, *RETRY_DELAYS)):
            if delay:
                self._sleep(delay)
            self._pace()
            self._ledger.check()  # every attempt counts against the quota
            try:
                response = self._http.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                raise ScorerError("gemini_network") from exc
            self._ledger.add()
            if response.status_code in RETRYABLE and attempt < len(RETRY_DELAYS):
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ScorerError(f"gemini_http_{response.status_code}") from exc
            return response
        raise ScorerError("gemini_failed")

    def score(self, request: ScoringRequest) -> str:
        prompt = build_prompt(request)
        self._ledger.check()
        url = f"{API_ROOT}/{self._model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": self._max_output,
                "responseMimeType": "application/json",
            },
        }
        # The key goes in a header, never in the URL, because request URLs are logged.
        headers = {"x-goog-api-key": self._key, "content-type": "application/json"}
        response = self._post(url, payload, headers)
        try:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ScorerError("gemini_bad_response") from exc
        return strip_fence(text)