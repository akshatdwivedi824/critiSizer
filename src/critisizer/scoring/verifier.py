"""Checks a scorer's raw answer. Nothing unverified gets past this file."""

import json
import re
import unicodedata
from dataclasses import dataclass, field

from critisizer.scoring.contract import (
    ASPECT_CODES,
    IndicatorDraft,
    Quote,
    SourceExcerpt,
)

MAX_QUOTE_CHARS = 300
MAX_NAME_CHARS = 200

_QUOTES = str.maketrans(
    {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class AnswerError(ValueError):
    """The scorer's answer broke a rule. The message says which one."""


@dataclass
class Rejection:
    reason: str
    raw: object


@dataclass
class VerifyResult:
    accepted: list[IndicatorDraft] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)


def normalise(text: str) -> str:
    """Compare quotes without caring about case, spacing or curly quotes."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    return " ".join(text.split()).casefold()


def parse_answer(raw: str) -> list[object]:
    text = _FENCE.sub("", raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnswerError(f"answer is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("indicators"), list):
        raise AnswerError('answer must be an object with an "indicators" list')
    return data["indicators"]


def _check_quote(entry: object, excerpts: dict[int, SourceExcerpt]) -> Quote:
    if not isinstance(entry, dict):
        raise AnswerError("evidence entry is not an object")
    source_id = entry.get("source_id")
    quote = entry.get("quote")
    if isinstance(source_id, bool) or not isinstance(source_id, int):
        raise AnswerError("source_id must be a whole number")
    if source_id not in excerpts:
        raise AnswerError(f"unknown source_id {source_id}")
    if not isinstance(quote, str) or not quote.strip():
        raise AnswerError("quote is empty")
    if len(quote) > MAX_QUOTE_CHARS:
        raise AnswerError(f"quote is longer than {MAX_QUOTE_CHARS} characters")
    if normalise(quote) not in normalise(excerpts[source_id].text):
        raise AnswerError(f"quote not found in source {source_id}")
    return Quote(source_id=source_id, text=quote.strip())


def _check_indicator(
    item: object,
    excerpts: dict[int, SourceExcerpt],
    aspect_codes: tuple[str, ...],
) -> IndicatorDraft:
    if not isinstance(item, dict):
        raise AnswerError("indicator is not an object")
    aspect = item.get("aspect")
    if not isinstance(aspect, str) or aspect not in aspect_codes:
        raise AnswerError(f"unknown aspect: {aspect!r}")
    name = item.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME_CHARS:
        raise AnswerError(f"name must be 1 to {MAX_NAME_CHARS} characters")
    description = item.get("description")
    if not isinstance(description, str) or not description.strip():
        raise AnswerError("description is missing")
    score = item.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 100:
        raise AnswerError(f"score must be a whole number from 1 to 100, got {score!r}")
    evidence = item.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise AnswerError("at least one quote is required")
    quotes = [_check_quote(entry, excerpts) for entry in evidence]
    return IndicatorDraft(aspect, name.strip(), score, description.strip(), quotes)


def verify_answer(
    raw: str,
    excerpts: list[SourceExcerpt],
    aspect_codes: tuple[str, ...] = ASPECT_CODES,
) -> VerifyResult:
    """Accept each indicator that passes every rule, and record why the rest
    were rejected. A badly shaped answer is rejected whole."""
    result = VerifyResult()
    try:
        items = parse_answer(raw)
    except AnswerError as exc:
        result.rejected.append(Rejection(str(exc), raw))
        return result
    by_id = {e.id: e for e in excerpts}
    for item in items:
        try:
            result.accepted.append(_check_indicator(item, by_id, aspect_codes))
        except AnswerError as exc:
            result.rejected.append(Rejection(str(exc), item))
    return result