"""Local model through Ollama: free, for development."""

from __future__ import annotations

from typing import Any

import httpx

from critisizer.scoring.contract import ScorerError, ScoringRequest
from critisizer.scoring.prompt import build_prompt

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen2.5:7b"


class OllamaScorer:
    def __init__(
        self, model: str = DEFAULT_MODEL, http: Any = None, url: str = OLLAMA_URL
    ) -> None:
        self.name = f"ollama:{model}"
        self._model = model
        self._url = url
        self._http = http or httpx.Client(timeout=600.0)

    def score(self, request: ScoringRequest) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": build_prompt(request)}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_ctx": 8192},
        }
        try:
            response = self._http.post(self._url, json=payload)
            response.raise_for_status()
            return response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ScorerError("ollama_failed") from exc