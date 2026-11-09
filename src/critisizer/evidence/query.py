"""The fixed search recipe. Same policy name in, same query out, every time."""

from __future__ import annotations

from critisizer.evidence.outlets import ALLOWED

QUERY_VERSION = "query_v1"
TIMESPAN = "3months"
MAX_RECORDS = 50

_TRAILING_GENERIC = {"scheme", "act", "policy", "rollout", "programme", "program"}


# Fixed per-policy search phrases, part of query_v1. Reviewed by hand.
PHRASES: dict[str, str] = {
    "demonetisation-2016": "Demonetisation",
    "gst-rollout-2017": "GST",
    "farm-laws-2020": "farm laws",
    "agnipath-scheme-2022": "Agnipath",
    "electoral-bonds-scheme-2018": "electoral bonds",
    "dpdp-act-2023": "Digital Personal Data Protection",
    "telecommunications-act-2023": "Telecommunications Act",
    "spectrum-allocation-2g-2008": "2G spectrum",
}


def search_phrase(policy_name: str, slug: str | None = None) -> str:
    """Fixed phrase for known slugs; otherwise drop generic trailing words."""
    if slug in PHRASES:
        return PHRASES[slug]
    words = policy_name.replace('"', "").split()
    while len(words) > 1 and words[-1].casefold() in _TRAILING_GENERIC:
        words.pop()
    return " ".join(words)


def build_query(phrase: str) -> str:
    domains = " OR ".join(f"domain:{d}" for d in sorted(ALLOWED))
    return f'"{phrase}" sourcelang:english ({domains})'