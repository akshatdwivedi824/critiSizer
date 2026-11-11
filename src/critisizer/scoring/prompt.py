from pathlib import Path

from critisizer.scoring.contract import ScoringRequest, SourceExcerpt
from critisizer.scoring.sentences import split_sentences

PROMPT_VERSION = "prompt_v3"  # single pass over all aspects: kept as history
ASPECT_PROMPT_VERSION = "prompt_v4"  # one aspect per call: the current method
_PROMPTS = Path(__file__).parent / "prompts"
_TEMPLATE = _PROMPTS / "score_v3.txt"
_ASPECT_TEMPLATE = _PROMPTS / "score_v4.txt"

ASPECT_DEFINITIONS = {
    "outcome_failure": (
        "how far official results fall short of the policy's own stated targets."
    ),
    "cost_waste": (
        "spending beyond budget, delay-driven cost, leakage or misuse of funds."
    ),
    "transparency_gap": (
        "information that should be public but is missing, withheld or contradicted."
    ),
    "ground_level_harm": (
        "documented negative effects on people where the policy is delivered."
    ),
    "legal_challenges": (
        "court cases and rulings against or questioning the policy."
    ),
    "equity_impact": (
        "unequal burden or side effects on particular groups, regions or sectors."
    ),
}


def format_excerpt(item: SourceExcerpt) -> str:
    """One source, its sentences numbered so the model can cite by number."""
    date = item.published or "undated"
    lines = [f"[{item.id}] {item.outlet}, {date}:"]
    for number, sentence in enumerate(split_sentences(item.text), start=1):
        lines.append(f"  ({number}) {sentence}")
    return "\n".join(lines)


def valid_citations(excerpts: list[SourceExcerpt]) -> str:
    """Tell the model which sentence numbers exist, so it cannot cite past the end."""
    parts = []
    for item in excerpts:
        count = len(split_sentences(item.text))
        parts.append(
            f"source {item.id}: sentences 1 to {count}"
            if count
            else f"source {item.id}: none"
        )
    return "; ".join(parts)


def _fill(template: str, request: ScoringRequest, replacements: dict[str, str]) -> str:
    text = template.replace("{policy_name}", request.policy_name).replace(
        "{policy_year}", str(request.policy_year)
    )
    for key, value in replacements.items():
        text = text.replace(key, value)
    # The excerpts go in last, so text inside a source can never be mistaken
    # for a placeholder.
    excerpts = "\n".join(format_excerpt(e) for e in request.excerpts)
    return text.replace("{excerpts}", excerpts)


def build_prompt(request: ScoringRequest) -> str:
    """Fill the frozen template: v3 without an aspect, v4 with one."""
    if request.aspect is None:
        template = _TEMPLATE.read_text(encoding="utf-8")
        return _fill(template, request, {})
    definition = ASPECT_DEFINITIONS.get(request.aspect)
    if definition is None:
        raise ValueError(f"unknown aspect: {request.aspect}")
    template = _ASPECT_TEMPLATE.read_text(encoding="utf-8")
    return _fill(
        template,
        request,
        {
            "{aspect_code}": request.aspect,
            "{aspect_definition}": definition,
            "{valid_citations}": valid_citations(request.excerpts),
        },
    )