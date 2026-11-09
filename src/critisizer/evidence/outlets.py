"""Fixed allow-list of outlets we collect from. Changing it means a new query version."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Outlet:
    name: str
    tier: int


# Tier 2 = established national press. Outlets that block automated fetching
# (e.g. Business Standard returns 403) are left off: we cannot read their text.
ALLOWED: dict[str, Outlet] = {
    "thehindu.com": Outlet("The Hindu", 2),
    "indianexpress.com": Outlet("The Indian Express", 2),
    "hindustantimes.com": Outlet("Hindustan Times", 2),
    "timesofindia.indiatimes.com": Outlet("The Times of India", 2),
    "economictimes.indiatimes.com": Outlet("The Economic Times", 2),
    "livemint.com": Outlet("Mint", 2),
    "theprint.in": Outlet("ThePrint", 2),
    "scroll.in": Outlet("Scroll", 2),
    "thewire.in": Outlet("The Wire", 2),
    "ndtv.com": Outlet("NDTV", 2),
    "deccanherald.com": Outlet("Deccan Herald", 2),
    "tribuneindia.com": Outlet("The Tribune", 2),
}


def normalise_domain(domain: str) -> str:
    value = domain.strip().lower()
    return value.removeprefix("www.")


def outlet_for(domain: str) -> Outlet | None:
    return ALLOWED.get(normalise_domain(domain))