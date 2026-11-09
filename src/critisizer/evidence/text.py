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


def make_excerpt(
    title: str, text: str, phrase: str, max_chars: int = MAX_EXCERPT_CHARS
) -> str | None:
    """Title + the article's opening text, capped. None for a passing mention.

    An article counts as being about the policy when the phrase is in the title
    or appears at least MIN_MENTIONS times in the body.
    """
    needle = phrase.casefold()
    paragraphs = [
        p.strip() for p in text.split("\n") if len(p.strip()) >= MIN_PARAGRAPH_CHARS
    ]
    mentions = sum(p.casefold().count(needle) for p in paragraphs)
    if needle not in title.casefold() and mentions < MIN_MENTIONS:
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