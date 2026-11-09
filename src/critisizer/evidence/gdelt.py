"""GDELT DOC 2.0 article search: free, no key, one request per 5 seconds."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from critisizer.evidence.query import MAX_RECORDS, TIMESPAN

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MIN_GAP_SECONDS = 6.0
RETRY_DELAYS = (0.0, 60.0, 180.0)  # seconds to wait before attempts 1, 2, 3


class CollectError(Exception):
    """Collecting failed. The message is a short code, not prose."""


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    domain: str
    published_at: datetime | None


def parse_seendate(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_articles(body: str) -> list[Article]:
    if not body.strip():
        return []  # GDELT answers an empty body when nothing matches
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CollectError("not_json") from exc  # e.g. the rate-limit notice
    if not isinstance(data, dict):
        raise CollectError("bad_shape")
    articles = []
    for row in data.get("articles", []):
        url = row.get("url")
        if not isinstance(url, str) or not url:
            continue
        articles.append(
            Article(
                url=url,
                title=" ".join(str(row.get("title", "")).split()),
                domain=str(row.get("domain", "")),
                published_at=parse_seendate(row.get("seendate")),
            )
        )
    return articles


class GdeltClient:
    def __init__(
        self,
        http: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http or httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "critiSizer/0.1 (research project)"},
        )
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def _wait(self) -> None:
        if self._last is not None:
            gap = MIN_GAP_SECONDS - (self._clock() - self._last)
            if gap > 0:
                self._sleep(gap)
        self._last = self._clock()

    def _get(self, params: dict[str, str]) -> str:
        self._wait()
        response = self._http.get(GDELT_URL, params=params)
        if response.status_code == 429:
            raise CollectError("rate_limited")
        response.raise_for_status()
        return response.text

    def search(self, query: str) -> tuple[str, list[Article]]:
        params = {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(MAX_RECORDS),
            "timespan": TIMESPAN,
            "sort": "hybridrel",
        }
        for delay in RETRY_DELAYS:
            if delay:
                self._sleep(delay)
            try:
                body = self._get(params)
                return body, parse_articles(body)
            except CollectError:
                continue  # rate-limit notice or 429: wait longer, try again
        raise CollectError("gave_up")