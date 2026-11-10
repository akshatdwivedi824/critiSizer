"""The fixed search recipe. Same policy in, same query out, every time."""

from __future__ import annotations

from critisizer.evidence.outlets import ALLOWED

QUERY_VERSION = "query_v2"
TIMESPAN = "3months"
MAX_RECORDS = 50

_TRAILING_GENERIC = {"scheme", "act", "policy", "rollout", "programme", "program"}

# Fixed per-policy phrases, first one primary. Part of the query version.
PHRASES: dict[str, tuple[str, ...]] = {
    "demonetisation-2016": ("Demonetisation", "note ban"),
    "gst-rollout-2017": ("GST", "Goods and Services Tax"),
    "farm-laws-2020": ("farm laws", "farm bills"),
    "agnipath-scheme-2022": ("Agnipath", "Agniveer"),
    "electoral-bonds-scheme-2018": ("electoral bonds", "electoral bond"),
    "dpdp-act-2023": ("Digital Personal Data Protection", "DPDP"),
    "telecommunications-act-2023": (
        "Telecommunications Act",
        "Telecom Act",
        "Telecommunications Bill",
        "Telecom Bill",
    ),
    "spectrum-allocation-2g-2008": ("2G spectrum", "2G scam"),
}


def search_phrases(policy_name: str, slug: str | None = None) -> tuple[str, ...]:
    """Fixed phrases for known slugs; otherwise the name minus generic tail words."""
    if slug in PHRASES:
        return PHRASES[slug]
    words = policy_name.replace('"', "").split()
    while len(words) > 1 and words[-1].casefold() in _TRAILING_GENERIC:
        words.pop()
    return (" ".join(words),)


def search_phrase(policy_name: str, slug: str | None = None) -> str:
    return search_phrases(policy_name, slug)[0]


def build_query(phrases: str | tuple[str, ...]) -> str:
    terms = (phrases,) if isinstance(phrases, str) else phrases
    quoted = " OR ".join(f'"{term}"' for term in terms)
    if len(terms) > 1:
        quoted = f"({quoted})"
    domains = " OR ".join(f"domain:{d}" for d in sorted(ALLOWED))
    return f"{quoted} sourcelang:english ({domains})"