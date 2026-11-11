from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from critisizer.deps import SessionDep
from critisizer.models import Policy
from critisizer.schemas import REVIEW_NOTE, AspectScoreOut
from critisizer.scorecard import (
    build_policy_detail,
    build_policy_summary,
    load_active_rubric,
    policy_progress,
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
.quote { margin: .25rem 0 .25rem 0; padding-left: .75rem; border-left: 3px solid #8885;
         font-style: italic; }
.excluded { text-decoration: line-through; opacity: .6; }
.muted { opacity: .65; }
a { color: inherit; }
"""

DISCLAIMER = (
    "Scores are editorial and record negatives only; this is not a full "
    "evaluation of any policy. Higher means more documented problems. "
    f"{REVIEW_NOTE}."
)

NOT_SCORED = (
    "Scores appear here once documented evidence has been collected and reviewed."
)

NO_OVERALL = (
    "There is no overall rating until a reviewer has resolved every aspect, "
    "so the figures below are partial."
)

NONE_FOUND = "No negative evidence found in the collected sources"


def layout(title: str, body: str) -> HTMLResponse:
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
        f"<p class='note'>{DISCLAIMER}</p>{body}</body></html>"
    )
    return HTMLResponse(html)


def _fmt(score: float | None) -> str:
    return "n/a" if score is None else f"{score:.1f}"


def _depth(sources: int, outlets: int) -> str:
    if not sources:
        return ""
    return f"Based on {sources} collected sources from {outlets} outlets."


@router.get("/", response_class=HTMLResponse)
def index(session: SessionDep) -> HTMLResponse:
    policies = session.scalars(select(Policy).order_by(Policy.name)).all()
    cards = []
    rubric = None
    for policy in policies:
        progress = policy_progress(session, policy.id)
        link = (
            f"<a href='/policies/{escape(policy.slug)}'>"
            f"<strong>{escape(policy.name)}</strong></a> ({policy.year})"
        )
        blurb = f"<span class='note'>{escape(policy.summary or '')}</span>"
        if progress.resolved == 0:
            cards.append(
                f"<div class='card'><span class='score'>Not yet scored</span> "
                f"{link}<br>{blurb}</div>"
            )
        elif not progress.rated:
            cards.append(
                f"<div class='card'><span class='score'>Under review: "
                f"{progress.resolved} of {progress.total} aspects resolved</span> "
                f"{link}<br>{blurb}</div>"
            )
        else:
            if rubric is None:
                rubric = load_active_rubric(session)
            view = build_policy_summary(session, policy, rubric)
            spike = " <span class='spike'>SPIKE</span>" if view.spike_flag else ""
            cards.append(
                f"<div class='card'><span class='score big'>"
                f"{view.overall_rating:.1f}</span>{spike} {link}<br>{blurb}</div>"
            )
    if not policies:
        cards = ["<p>No policies yet. Run <code>scripts/seed.py</code>.</p>"]
    return layout("critiSizer", f"<h1>critiSizer</h1>{''.join(cards)}")


def _evidence_html(indicator) -> str:
    out = ""
    for ev in indicator.evidence:
        css = "ev excluded" if ev.excluded else "ev"
        tag = " (excluded)" if ev.excluded else ""
        outlet = f" &middot; {escape(ev.outlet)}" if ev.outlet else ""
        quote = (
            f"<div class='quote'>&ldquo;{escape(ev.quote)}&rdquo;</div>"
            if ev.quote
            else ""
        )
        out += (
            f"<div class='{css}'>{quote}Tier {ev.source_tier}, x{ev.multiplier}: "
            f"<a href='{escape(ev.source_url)}'>{escape(ev.source_title)}</a>"
            f"{outlet}{tag}</div>"
        )
    return out


def _aspect_card(aspect: AspectScoreOut) -> str:
    heading = escape(aspect.name)
    if aspect.status == "scored":
        rows = "".join(
            f"<div class='ind'><span class='score'>{ind.score:.0f}</span> "
            f"{escape(ind.name)}"
            f"<br><span class='note'>{escape(ind.description or '')}</span>"
            f"{_evidence_html(ind)}</div>"
            for ind in aspect.indicators
        )
        return (
            f"<div class='card'><h3>{heading} "
            f"<span class='score'>{_fmt(aspect.score)}</span></h3>{rows}</div>"
        )
    if aspect.status == "no_negative_evidence":
        reason = (
            f"<br><span class='note'>Reviewer note: {escape(aspect.review_reason)}"
            "</span>"
            if aspect.review_reason
            else ""
        )
        return (
            f"<div class='card'><h3>{heading} "
            f"<span class='score'>{_fmt(aspect.score)}</span></h3>"
            f"{NONE_FOUND}.{reason}</div>"
        )
    return (
        f"<div class='card muted'><h3>{heading}</h3>"
        "Not yet reviewed.</div>"
    )


@router.get("/policies/{slug}", response_class=HTMLResponse)
def policy_page(slug: str, session: SessionDep) -> HTMLResponse:
    policy = session.scalar(select(Policy).where(Policy.slug == slug))
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")

    head = (
        "<p><a href='/'>&larr; All policies</a></p>"
        f"<h1>{escape(policy.name)} ({policy.year})</h1>"
        f"<p>{escape(policy.summary or '')}</p>"
    )

    if policy_progress(session, policy.id).resolved == 0:
        body = (
            f"{head}<div class='card'><span class='score'>Not yet scored</span><br>"
            f"<span class='note'>{NOT_SCORED}</span></div>"
        )
        return layout(policy.name, body)

    rubric = load_active_rubric(session)
    view = build_policy_detail(session, policy, rubric)
    depth = _depth(view.source_count, view.outlet_count)
    depth_html = f"<br><span class='note'>{depth}</span>" if depth else ""

    if view.rated:
        if view.people_rating is not None:
            people = f"{view.people_rating:.1f} ({view.people_rating_count} ratings)"
        else:
            people = f"not shown yet ({view.people_rating_count} ratings so far)"
        spike = (
            " &middot; <span class='spike'>Spike flag</span>"
            if view.spike_flag
            else ""
        )
        summary_card = (
            f"<div class='card'><span class='score big'>{view.overall_rating:.1f}"
            f"</span> overall{spike}<br>Expert average {view.expert_average:.1f}"
            f" &middot; People's rating: {people}{depth_html}<br>"
            f"<span class='note'>Rubric {escape(view.rubric_label)}</span></div>"
        )
    else:
        summary_card = (
            f"<div class='card'><span class='score big'>Under review: "
            f"{view.aspects_resolved} of {view.aspects_total} aspects resolved"
            f"</span><br><span class='note'>{NO_OVERALL}</span>{depth_html}</div>"
        )

    sections = "".join(_aspect_card(a) for a in view.aspects)
    return layout(view.name, f"{head}{summary_card}{sections}")