"""Split excerpt text into numbered sentences so a model can cite by number."""

from __future__ import annotations

import re

MIN_SENTENCE_CHARS = 30
MAX_SENTENCE_CHARS = 300
_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Deterministic split. Only sentences that can be cited are kept."""
    sentences = []
    for line in text.split("\n"):
        for piece in _BOUNDARY.split(line.strip()):
            cleaned = " ".join(piece.split())
            if MIN_SENTENCE_CHARS <= len(cleaned) <= MAX_SENTENCE_CHARS:
                sentences.append(cleaned)
    return sentences