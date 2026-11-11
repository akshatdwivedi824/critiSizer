"""Split excerpt text into numbered sentences so a model can cite by number."""

from __future__ import annotations

import re

MIN_SENTENCE_CHARS = 30
MAX_SENTENCE_CHARS = 300
_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
# A full stop after one of these is not the end of a sentence.
_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "no.", "nos.", "rs.", "vs.", "v.",
    "st.", "sr.", "jr.", "inc.", "ltd.", "co.", "hon.", "govt.", "cr.", "lt.",
    "gen.", "col.", "capt.", "adv.", "dept.",
}  # fmt: skip
# Initials such as "J." or "J.B." (and "i.e.", "e.g.").
_INITIALS = re.compile(r"(?:[a-z]\.){1,3}")


def _ends_with_abbreviation(piece: str) -> bool:
    tokens = piece.split()
    if not tokens:
        return False
    last = tokens[-1].casefold()
    return last in _ABBREVIATIONS or _INITIALS.fullmatch(last) is not None


def _pieces(line: str) -> list[str]:
    merged: list[str] = []
    for piece in _BOUNDARY.split(line.strip()):
        if merged and _ends_with_abbreviation(merged[-1]):
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return merged


def split_sentences(text: str) -> list[str]:
    """Deterministic split. Only sentences that can be cited are kept."""
    sentences = []
    for line in text.split("\n"):
        for piece in _pieces(line):
            cleaned = " ".join(piece.split())
            if MIN_SENTENCE_CHARS <= len(cleaned) <= MAX_SENTENCE_CHARS:
                sentences.append(cleaned)
    return sentences