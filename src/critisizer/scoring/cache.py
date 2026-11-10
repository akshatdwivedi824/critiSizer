"""Answer cache: the same model + prompt + sources never costs twice."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from critisizer.scoring.contract import Scorer, ScoringRequest
from critisizer.scoring.prompt import PROMPT_VERSION, build_prompt

DEFAULT_DIR = Path(".cache") / "scoring"


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


class CachedScorer:
    def __init__(
        self, inner: Scorer, directory: Path = DEFAULT_DIR, run: int = 0
    ) -> None:
        self.inner = inner
        self.name = inner.name
        self._dir = Path(directory)
        self._run = run  # separate cache slot per repeat run (spread check)

    def _path(self, request: ScoringRequest) -> Path:
        key = f"{self.inner.name}|{PROMPT_VERSION}|{self._run}|{build_prompt(request)}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._dir / f"{digest}.json"

    def score(self, request: ScoringRequest) -> str:
        path = self._path(request)
        if path.exists():
            return path.read_text(encoding="utf-8")
        raw = self.inner.score(request)
        if _is_json(raw):  # never freeze a failed answer
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_text(raw, encoding="utf-8")
        return raw