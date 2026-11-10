"""Fetch an article page and keep its text, if it is actually about the policy."""

from __future__ import annotations

import trafilatura

MAX_EXCERPT_CHARS = 3000
MIN_PARAGRAPH_CHARS = 40
MIN_MENTIONS = 2


def fetch_article_text(url: str) -> str | None:
    html = trafilatura.fetch_url(url)
    if not html:
        return None
    return trafilatura.extract(html, include_comments=False, include_tables=False)


def _norm(value: str) -> str:
    """Compare ignoring case and the s/z spelling split (demonetisation/ization)."""
    return value.casefold().replace("z", "s")


def make_excerpt(
    title: str,
    text: str,
    phrases: str | tuple[str, ...],
    max_chars: int = MAX_EXCERPT_CHARS,
) -> str | None:
    """Title + the article's opening text, capped. None for a passing mention.

    An article is about the policy when any phrase is in the title, or the
    phrases appear at least MIN_MENTIONS times in the body.
    """
    needles = [_norm(p) for p in ((phrases,) if isinstance(phrases, str) else phrases)]
    paragraphs = [
        p.strip() for p in text.split("\n") if len(p.strip()) >= MIN_PARAGRAPH_CHARS
    ]
    mentions = sum(_norm(p).count(n) for p in paragraphs for n in needles)
    in_title = any(n in _norm(title) for n in needles)
    if not in_title and mentions < MIN_MENTIONS:
        return None
    chosen: list[str] = []
    used = 0
    for paragraph in paragraphs:
        room = max_chars - used
        if room <= 0:
            break
        piece = paragraph[:room]
        chosen.append(piece)
        used += len(piece) + 1
    return f"{title}\n" + "\n".join(chosen)