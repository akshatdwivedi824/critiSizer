from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.models import Aspect, Evidence, Indicator, Policy

router = APIRouter()

CSS = """
:root { color-scheme: light dark; }
body { font-family: system-ui, sans-serif; max-width: 52rem; margin: 2rem auto;
       padding: 0 1rem; line-height: 1.5; }
.note { font-size: .85rem; opacity: .75; }
.card { border: 1px solid #8884; border-radius: .5rem; padding: .75rem 1rem;
        margin: .75rem 0; }
.ind { border-top: 1px solid #8883; padding: .5rem 0; }
.score { font-weight: 700; }
.ev { font-size: .9rem; margin-left: 1rem; }
.excluded { text-decoration: line-through; opacity: .6; }
a { color: inherit; }
"""

DISCLAIMER = (
    "Fictional test data. This scorecard records negatives only "
    "and is not a full evaluation of any policy."
)


def layout(title: str, body: str) -> HTMLResponse:
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
        f"<p class='note'>{DISCLAIMER}</p>{body}</body></html>"
    )
    return HTMLResponse(html)


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    with SessionLocal() as session:
        rows = session.execute(
            select(Policy.slug, Policy.name, Policy.year, Policy.summary).order_by(
                Policy.name
            )
        ).all()
    if rows:
        cards = "".join(
            f"<div class='card'><a href='/policies/{escape(slug)}'>"
            f"<strong>{escape(name)}</strong></a> ({year})"
            f"<br><span class='note'>{escape(summary or '')}</span></div>"
            for slug, name, year, summary in rows
        )
    else:
        cards = "<p>No policies yet. Run <code>scripts/seed.py</code>.</p>"
    return layout("critiSizer", f"<h1>critiSizer</h1>{cards}")


@router.get("/policies/{slug}", response_class=HTMLResponse)
def policy_page(slug: str) -> HTMLResponse:
    with SessionLocal() as session:
        policy = session.scalar(select(Policy).where(Policy.slug == slug))
        if policy is None:
            raise HTTPException(status_code=404, detail="Policy not found")
        aspects = session.scalars(select(Aspect).order_by(Aspect.id)).all()
        indicators = session.scalars(
            select(Indicator)
            .where(Indicator.policy_id == policy.id)
            .order_by(Indicator.id)
        ).all()
        evidence = session.scalars(
            select(Evidence).where(Evidence.indicator_id.in_([i.id for i in indicators]))
        ).all()

        ev_by_ind: dict[int, list[Evidence]] = {}
        for ev in evidence:
            ev_by_ind.setdefault(ev.indicator_id, []).append(ev)

        sections = []
        for aspect in aspects:
            items = [i for i in indicators if i.aspect_id == aspect.id]
            if not items:
                continue
            rows = []
            for ind in items:
                ev_html = "".join(
                    f"<div class='ev{' excluded' if ev.verification_multiplier == 0 else ''}'>"
                    f"Tier {ev.source_tier}, x{ev.verification_multiplier}: "
                    f"<a href='{escape(ev.source_url)}'>{escape(ev.source_title)}</a>"
                    f"{' (excluded)' if ev.verification_multiplier == 0 else ''}</div>"
                    for ev in ev_by_ind.get(ind.id, [])
                )
                rows.append(
                    f"<div class='ind'><span class='score'>{ind.score:.0f}</span> "
                    f"{escape(ind.name)}"
                    f"<br><span class='note'>{escape(ind.description or '')}</span>"
                    f"{ev_html}</div>"
                )
            sections.append(
                f"<div class='card'><h3>{escape(aspect.name)}</h3>{''.join(rows)}</div>"
            )

        body = (
            "<p><a href='/'>&larr; All policies</a></p>"
            f"<h1>{escape(policy.name)} ({policy.year})</h1>"
            f"<p>{escape(policy.summary or '')}</p>{''.join(sections)}"
        )
        title = policy.name
    return layout(title, body)