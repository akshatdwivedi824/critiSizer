"""Hosted model (Anthropic API) with a hard token budget. Final pilot only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from critisizer.scoring.contract import ScorerError, ScoringRequest
from critisizer.scoring.prompt import build_prompt

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-haiku-5-5"
LEDGER = Path(".cache") / "scoring" / "ledger.json"


class Budget:
    """Total tokens we allow ourselves to spend. Refuses calls past the cap."""

    def __init__(self, path: Path, max_tokens: int) -> None:
        self._path = Path(path)
        self._max = max_tokens

    def used(self) -> int:
        try:
            return int(json.loads(self._path.read_text(encoding="utf-8"))["tokens"])
        except (OSError, ValueError, KeyError):
            return 0

    def check(self, estimate: int) -> None:
        if self.used() + estimate > self._max:
            raise ScorerError("budget_exhausted")

    def add(self, tokens: int) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        total = self.used() + tokens
        self._path.write_text(json.dumps({"tokens": total}), encoding="utf-8")


def strip_fence(text: str) -> str:
    """Models sometimes wrap JSON in a code fence; remove it."""
    value = text.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[1] if "\n" in value else ""
        value = value.removesuffix("```").strip()
    return value


class AnthropicScorer:
    def __init__(
        self,
        api_key: str,
        budget: Budget,
        model: str = DEFAULT_MODEL,
        http: Any = None,
        max_output: int = 2000,
    ) -> None:
        if not api_key:
            raise ScorerError("no_api_key")
        self.name = f"anthropic:{model}"
        self._key = api_key
        self._budget = budget
        self._model = model
        self._max_output = max_output
        self._http = http or httpx.Client(timeout=120.0)

    def score(self, request: ScoringRequest) -> str:
        prompt = build_prompt(request)
        # Cautious upper bound on tokens for this call, checked before sending.
        self._budget.check(len(prompt) // 3 + self._max_output)
        payload = {
            "model": self._model,
            "max_tokens": self._max_output,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": self._key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            response = self._http.post(API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            text = data["content"][0]["text"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise ScorerError("hosted_failed") from exc
        usage = data.get("usage", {})
        spent = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
        self._budget.add(spent)
        return strip_fence(text)