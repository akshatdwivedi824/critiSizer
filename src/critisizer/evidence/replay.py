"""Stand-in for the GDELT client that reads a saved response from a file.

Used for development and demos so nothing depends on a free API being available.
"""

from __future__ import annotations

from pathlib import Path

from critisizer.evidence.gdelt import Article, parse_articles


class ReplayClient:
    def __init__(self, path: str | Path) -> None:
        self._body = Path(path).read_text(encoding="utf-8-sig")

    def search(self, query: str) -> tuple[str, list[Article]]:
        return self._body, parse_articles(self._body)