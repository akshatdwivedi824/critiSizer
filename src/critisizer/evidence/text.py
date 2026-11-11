"""Fetch an article page and keep its text, if it is actually about the policy."""

from __future__ import annotations

import re

import trafilatura

# Bump when the cleaning rules change, so old and new excerpts can be told apart.
EXTRACTION_VERSION = "text_v2"

MAX_EXCERPT_CHARS = 3000
MIN_PARAGRAPH_CHARS = 40
MIN_MENTIONS = 2

# A sentence end glued straight onto the next sentence: a caption or heading
# that the extractor joined without a space ("...demonetisation.People stood...").
_MISSING_SPACE = re.compile(r"(?<=[a-z0-9][.!?])(?=[A-Z][a-z])|(?<=[.!?][\"\u201d\u2019])(?=[A-Z][a-z])")
# Lines that are page furniture, not reporting.
_PREFIX = re.compile(
    r"^\s*(?:(?:also read|read more|advertisement|follow us)\b"
    r"|(?:file photo|representational image|photo credit|pti photo|photo|image)"
    r"\s*[:(\-\u2013/])",
    re.IGNORECASE,
)
_ANYWHERE = re.compile(
    r"enable javascript|javascript (?:is )?(?:disabled|required)|accept (?:all )?cookies"
    r"|cookie (?:policy|settings)|subscribe to (?:continue|read)"
    r"|sign in to (?:continue|read)|access denied|are you a (?:robot|human)"
    r"|captcha|all rights reserved",
    re.IGNORECASE,
)
# A photo credit riding on the end of a real paragraph.
_CREDIT_TAIL = re.compile(
    r"\s*\b(?:photo|image|file photo|representational image)\s*:.*$", re.IGNORECASE
)


def fetch_article_text(url: str) -> str | None:
    html = trafilatura.fetch_url(url)
    if not html:
        return None
    return trafilatura.extract(html, include_comments=False, include_tables=False)


def _norm(value: str) -> str:
    """Compare ignoring case and the s/z spelling split (demonetisation/ization)."""
    return value.casefold().replace("z", "s")


def clean_paragraph(paragraph: str) -> str | None:
    """One line of article text, repaired. None if it is page furniture."""
    text = _CREDIT_TAIL.sub("", paragraph.strip()).strip()
    if not text or _PREFIX.match(text) or _ANYWHERE.search(text):
        return None
    return _MISSING_SPACE.sub(" ", text)


def make_excerpt(
    title: str,
    text: str,
    phrases: str | tuple[str, ...],
    max_chars: int = MAX_EXCERPT_CHARS,
) -> str | None:
    """Title + the article's opening text, capped. None for a passing mention.

    An article is about the policy when the body mentions a phrase and either a
    phrase is in the title or the body mentions them at least MIN_MENTIONS times.
    A page whose body never mentions the policy (a paywall or an error page that
    only shares a headline) is not an excerpt.
    """
    needles = [_norm(p) for p in ((phrases,) if isinstance(phrases, str) else phrases)]
    paragraphs = []
    for line in text.split("\n"):
        cleaned = clean_paragraph(line)
        if cleaned is not None and len(cleaned) >= MIN_PARAGRAPH_CHARS:
            paragraphs.append(cleaned)
    mentions = sum(_norm(p).count(n) for p in paragraphs for n in needles)
    in_title = any(n in _norm(title) for n in needles)
    if mentions == 0 or (not in_title and mentions < MIN_MENTIONS):
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