"""Development only: replay files from known article URLs, then collect them.

The live system finds articles through GDELT. This exists so the pipeline can be
worked on while GDELT is unavailable. Page text is still fetched for real.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.evidence.collect import collect_for_policy, enough_to_score
from critisizer.evidence.replay import ReplayClient
from critisizer.models import Policy

logger = logging.getLogger("dev_replay")
OUT = Path("data/replay")

ARTICLES: dict[str, list[tuple[str, str]]] = {
    "agnipath-scheme-2022": [
        ("https://theprint.in/opinion/revised-agnipath-leaves-fundamental-flaws-unaddressed/3091915/",
         "Revised Agnipath leaves fundamental flaws unaddressed"),
        ("https://www.tribuneindia.com/news/editorials/reviewing-agnipath-624198",
         "Reviewing Agnipath"),
        ("https://tribuneindia.com/news/agnipath-row-644284", "Agnipath row"),
        ("https://theprint.in/opinion/agnipath-scheme-has-turned-into-political-football-time-to-strike-a-consensus-on-its-tenure/2186373",
         "Agnipath scheme has turned into political football, time to strike a consensus on its tenure"),
        ("https://theprint.in/defence/recruiting-agniveers-for-7-8-yrs-retaining-60-70-afterwards-possible-changes-to-agnipath-scheme/2130092",
         "Recruiting Agniveers for 7-8 yrs, retaining 60-70% afterwards: possible changes to Agnipath scheme"),
        ("https://deccanherald.com/opinion/agniveer-scheme-should-not-upset-the-capf-applecart-3122736",
         "Agniveer scheme should not upset the CAPF applecart"),
    ],
    "demonetisation-2016": [
        ("https://theprint.in/opinion/by-a-99-3-verdict-indias-cash-ban-was-a-farce/108496",
         "By a 99.3% verdict, India's cash ban was a farce"),
        ("https://scroll.in/article/893522/scroll_in", "Demonetisation: RBI report"),
        ("https://thewire.in/economy/how-successful-was-demonetisation-four-takeaways-from-the-rbis-annual-report",
         "How successful was demonetisation? Four takeaways from the RBI's annual report"),
        ("https://thewire.in/economy/unprecedented-job-losses-wage-decline-unorganised-sector-post-demonetisation",
         "Unprecedented job losses, wage decline in unorganised sector post demonetisation"),
        ("https://thewire.in/economy/modis-demonetisation-move-may-have-permanently-damaged-indias-informal-sector",
         "Modi's demonetisation move may have permanently damaged India's informal sector"),
        ("https://thewire.in/economy/demonetisation-a-gimmick-to-distract-from-ineffectual-governance-say-civil-society-members",
         "Demonetisation a gimmick to distract from ineffectual governance, say civil society members"),
    ],
    "gst-rollout-2017": [
        ("https://scroll.in/article/851917/scroll_in", "GST rollout: Scroll"),
        ("https://www.tribuneindia.com/news/archive/features/miles-away-from-one-nation-one-tax-489432",
         "Miles away from one nation, one tax"),
        ("https://theprint.in/opinion/smes-gst-mountain-need-support/11595",
         "SMEs' GST mountain: need support"),
        ("https://thewire.in/economy/balancing-reform-and-reality-the-gst-dilemma-for-msmes",
         "Balancing reform and reality: the GST dilemma for MSMEs"),
    ],
    "farm-laws-2020": [
        ("https://theprint.in/india/protests-failed-talks-violence-deaths-timeline-of-farm-laws-before-modi-govts-u-turn/768410",
         "Protests, failed talks, violence, deaths: timeline of farm laws before Modi govt's U-turn"),
        ("https://scroll.in/latest/1020089/scroll_in",
         "Repealing farm laws unfair to 'silent majority' of farmers who supported reforms: SC panel report"),
        ("https://thewire.in/law/supreme-court-farm-laws-implemntation-stay-committee-talks",
         "SC stays implementation of farm laws, forms committee"),
    ],
    "electoral-bonds-scheme-2018": [
        ("https://thewire.in/law/supreme-court-electoral-bonds-quash-anonymous",
         "Supreme Court quashes electoral bonds, anonymous donations"),
        ("https://scroll.in/latest/1063719/supreme-court-strikes-down-electoral-bonds-scheme",
         "Supreme Court strikes down electoral bonds scheme"),
        ("https://www.deccanherald.com/india/electoral-bonds-data-sbi-ec-bjp-top-donors-qwik-supply-chain-reliance-megha-engineering-infrastructure-keventer-aditya-birla-bharti-airtel-lok-sabha-2947875",
         "Electoral bonds data: BJP's top donors"),
        ("https://theprint.in/economy/top-10-donors-to-bjp-via-electoral-bonds-megha-engg-reliance-linked-firm-keventers-group-top-list/2010905",
         "Top 10 donors to BJP via electoral bonds"),
        ("https://www.deccanherald.com/india/electoral-bonds-data-exposes-bjps-corrupt-tactics-congress-2937816",
         "Electoral bonds data exposes BJP's 'corrupt tactics': Congress"),
        ("https://www.tribuneindia.com/news/india/megha-engg-qwik-bjps-top-donors-603076",
         "Megha Engg, Qwik: BJP's top donors"),
    ],
    "dpdp-act-2023": [
        ("https://theprint.in/india/governance/doesnt-dilute-rti-act-vaishnaw-says-criticism-of-new-personal-data-protection-law-unfair/1713729",
         "Doesn't dilute RTI Act: Vaishnaw says criticism of new personal data protection law unfair"),
        ("https://deccanherald.com/india/karnataka/bengaluru/new-data-protection-law-draws-criticism-2648820",
         "New data protection law draws criticism"),
        ("https://www.tribuneindia.com/news/india/oppn-says-data-law-threat-to-rti-govt-cites-sc-judgment",
         "Oppn says data law threat to RTI, govt cites SC judgment"),
        ("https://thewire.in/government/opposition-activists-raise-alarm-as-modi-govt-gets-ready-to-pass-data-protection-bill",
         "Opposition, activists raise alarm as Modi govt gets ready to pass data protection bill"),
    ],
    "telecommunications-act-2023": [
        ("https://scroll.in/article/1060973/scroll_in", "Telecommunications Act: Scroll"),
        ("https://thewire.in/government/cleverly-drafted-telecom-bill-government-tightens-grip-digital-india",
         "Cleverly drafted telecom bill: government tightens grip on digital India"),
    ],
    "spectrum-allocation-2g-2008": [
        ("https://thewire.in/business/all-those-accused-in-2g-scam-case-acquitted-by-cbi-court",
         "All those accused in 2G scam case acquitted by CBI court"),
        ("https://www.deccanherald.com/india/timeline-2g-case-2039679", "Timeline: 2G case"),
        ("https://www.deccanherald.com/india/vinod-rai-bjp-should-apologise-2039708",
         "Vinod Rai, BJP should apologise"),
    ],
}


def write_replay(slug: str, items: list[tuple[str, str]]) -> Path:
    articles = [
        {
            "url": url,
            "title": title,
            "domain": urlparse(url).netloc.removeprefix("www."),
            "language": "English",
            "sourcecountry": "India",
        }
        for url, title in items
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{slug}.json"
    path.write_text(json.dumps({"articles": articles}, indent=1), encoding="utf-8")
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with SessionLocal() as session:
        for slug, items in ARTICLES.items():
            policy = session.scalar(select(Policy).where(Policy.slug == slug))
            if policy is None:
                logger.warning("%s: no such policy in the database", slug)
                continue
            path = write_replay(slug, items)
            report = collect_for_policy(session, policy, ReplayClient(path))
            session.commit()
            logger.info(
                "%-30s found %d stored %d skipped %s enough=%s",
                slug, report.found, report.stored, dict(report.skipped),
                enough_to_score(session, policy.id),
            )


if __name__ == "__main__":
    main()