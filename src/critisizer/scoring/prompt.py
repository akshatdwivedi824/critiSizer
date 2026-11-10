from pathlib import Path

from critisizer.scoring.contract import ScoringRequest, SourceExcerpt
from critisizer.scoring.sentences import split_sentences

PROMPT_VERSION = "prompt_v3"
_TEMPLATE = Path(__file__).parent / "prompts" / "score_v3.txt"


def format_excerpt(item: SourceExcerpt) -> str:
    """One source, its sentences numbered so the model can cite by number."""
    date = item.published or "undated"
    lines = [f"[{item.id}] {item.outlet}, {date}:"]
    for number, sentence in enumerate(split_sentences(item.text), start=1):
        lines.append(f"  ({number}) {sentence}")
    return "\n".join(lines)


def build_prompt(request: ScoringRequest) -> str:
    """Fill the frozen template. The excerpts go in last, so text inside a
    source can never be mistaken for a placeholder."""
    template = _TEMPLATE.read_text(encoding="utf-8")
    excerpts = "\n".join(format_excerpt(e) for e in request.excerpts)
    return (
        template.replace("{policy_name}", request.policy_name)
        .replace("{policy_year}", str(request.policy_year))
        .replace("{excerpts}", excerpts)
    )