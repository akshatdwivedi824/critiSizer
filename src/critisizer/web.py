from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from critisizer.deps import SessionDep
from critisizer.models import Policy
from critisizer.scorecard import (
    build_policy_detail,
    build_policy_summary,
    load_active_rubric,
)

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
.big { font-size: 1.8rem; }
.spike { color: #c0392b; font-weight: 700; }
.ev { font-size: .9rem; margin-left: 1rem; }
.excluded { text-decoration: line-through; opacity: .6; }
a { color: inherit; }
"""

DISCLAIMER = (
    "Fictional test data. This scorecard records negatives only "
    "and is not a full evaluation of any policy. Higher means more documented problems."
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
def index(session: SessionDep) -> HTMLResponse:
    policies = session.scalars(select(Policy).order_by(Policy.name)).all()
    cards = []
    if policies:
        rubric = load_active_rubric(session)
        for policy in policies:
            view = build_policy_summary(session, policy, rubric)
            spike = " <span class='spike'>SPIKE</span>" if view.spike_flag else ""
            cards.append(
                f"<div class='card'><span class='score big'>"
                f"{view.overall_rating:.1f}</span>{spike} "
                f"<a href='/policies/{escape(view.slug)}'>"
                f"<strong>{escape(view.name)}</strong></a> ({view.year})<br>"
                f"<span class='note'>{escape(view.summary or '')}</span></div>"
            )
    else:
        cards = ["<p>No policies yet. Run <code>scripts/seed.py</code>.</p>"]
    return layout("critiSizer", f"<h1>critiSizer</h1>{''.join(cards)}")


@router.get("/policies/{slug}", response_class=HTMLResponse)
def policy_page(slug: str, session: SessionDep) -> HTMLResponse:
    policy = session.scalar(select(Policy).where(Policy.slug == slug))
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    rubric = load_active_rubric(session)
    view = build_policy_detail(session, policy, rubric)

    sections = []
    for aspect in view.aspects:
        if not aspect.indicators:
            continue
        rows = []
        for ind in aspect.indicators:
            ev_html = ""
            for ev in ev_html_source(ind):
                css = "ev excluded" if ev.excluded else "ev"
                tag = " (excluded)" if ev.excluded else ""
                ev_html += (
                    f"<div class='{css}'>Tier {ev.source_tier}, x{ev.multiplier}: "
                    f"<a href='{escape(ev.source_url)}'>"
                    f"{escape(ev.source_title)}</a>{tag}</div>"
                )
            rows.append(
                f"<div class='ind'><span class='score'>{ind.score:.0f}</span> "
                f"{escape(ind.name)}"
                f"<br><span class='note'>{escape(ind.description or '')}</span>"
                f"{ev_html}</div>"
            )
        sections.append(
            f"<div class='card'><h3>{escape(aspect.name)} "
            f"<span class='score'>{aspect.score:.1f}</span></h3>{''.join(rows)}</div>"
        )

    if view.people_rating is not None:
        people = f"{view.people_rating:.1f} ({view.people_rating_count} ratings)"
    else:
        people = f"not shown yet ({view.people_rating_count} ratings so far)"
    spike = " &middot; <span class='spike'>Spike flag</span>" if view.spike_flag else ""
    summary_card = (
        f"<div class='card'><span class='score big'>{view.overall_rating:.1f}"
        f"</span> overall{spike}<br>Expert average {view.expert_average:.1f}"
        f" &middot; People's rating: {people}<br>"
        f"<span class='note'>Rubric {escape(view.rubric_label)}</span></div>"
    )
    body = (
        "<p><a href='/'>&larr; All policies</a></p>"
        f"<h1>{escape(view.name)} ({view.year})</h1>"
        f"<p>{escape(view.summary or '')}</p>{summary_card}{''.join(sections)}"
    )
    return layout(view.name, body)


def ev_html_source(indicator):
    return indicator.evidence
