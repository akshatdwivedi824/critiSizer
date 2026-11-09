"""Fetch an article page and cut out only the passages that mention the policy."""

from __future__ import annotations

import trafilatura

MAX_EXCERPT_CHARS = 1500
MIN_PARAGRAPH_CHARS = 40


def fetch_article_text(url: str) -> str | None:
    html = trafilatura.fetch_url(url)
    if not html:
        return None
    return trafilatura.extract(html, include_comments=False, include_tables=False)


def make_excerpt(
    title: str, text: str, phrase: str, max_chars: int = MAX_EXCERPT_CHARS
) -> str | None:
    """Title + the paragraphs that contain the phrase, capped. None if none do."""
    needle = phrase.casefold()
    hits = [
        p.strip()
        for p in text.split("\n")
        if len(p.strip()) >= MIN_PARAGRAPH_CHARS and needle in p.casefold()
    ]
    if not hits:
        return None
    chosen: list[str] = []
    used = 0
    for paragraph in hits:
        room = max_chars - used
        if room <= 0:
            break
        piece = paragraph[:room]
        chosen.append(piece)
        used += len(piece) + 1
    return f"{title}\n" + "\n".join(chosen)