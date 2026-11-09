from pathlib import Path

from critisizer.scoring.contract import ScoringRequest, SourceExcerpt

PROMPT_VERSION = "prompt_v1"
_TEMPLATE = Path(__file__).parent / "prompts" / "score_v1.txt"


def format_excerpt(item: SourceExcerpt) -> str:
    date = item.published or "undated"
    return f"[{item.id}] {item.outlet}, {date}: {' '.join(item.text.split())}"


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