"""Turn a model's sentence-number citations into verbatim quotes."""

from __future__ import annotations

import json

from critisizer.scoring.contract import SourceExcerpt
from critisizer.scoring.sentences import split_sentences


def resolve_citations(raw: str, excerpts: list[SourceExcerpt]) -> str:
    """Fill in 'quote' for evidence items given as {'source_id', 'sentence'}.

    Items with a bad source or sentence number get no quote, so the verifier
    rejects them. Items that already carry a quote are left alone.
    """
    try:
        data = json.loads(raw)
    except ValueError:
        return raw
    indicators = data.get("indicators") if isinstance(data, dict) else None
    if not isinstance(indicators, list):
        return raw
    by_id = {e.id: split_sentences(e.text) for e in excerpts}
    for indicator in indicators:
        evidence = indicator.get("evidence") if isinstance(indicator, dict) else None
        if not isinstance(evidence, list):
            continue
        for item in evidence:
            if not isinstance(item, dict) or "quote" in item:
                continue
            number = item.get("sentence")
            sentences = by_id.get(item.get("source_id"), [])
            valid = isinstance(number, int) and not isinstance(number, bool)
            if valid and 1 <= number <= len(sentences):
                item["quote"] = sentences[number - 1]
    return json.dumps(data)