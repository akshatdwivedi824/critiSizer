from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from critisizer.db import SessionLocal
from critisizer.models import Aspect, Evidence, Indicator, Policy
from critisizer.scorecard import load_active_rubric, score_policy

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
def index() -> HTMLResponse:
    with SessionLocal() as session:
        rows = session.execute(
            select(
                Policy.id, Policy.slug, Policy.name, Policy.year, Policy.summary
            ).order_by(Policy.name)
        ).all()
        rubric = load_active_rubric(session) if rows else None
        cards = []
        for policy_id, slug, name, year, summary in rows:
            result = score_policy(session, policy_id, rubric)
            spike = " <span class='spike'>SPIKE</span>" if result.spike_flag else ""
            cards.append(
                f"<div class='card'><span class='score big'>"
                f"{result.overall_rating:.1f}</span>{spike} "
                f"<a href='/policies/{escape(slug)}'><strong>{escape(name)}</strong>"
                f"</a> ({year})<br><span class='note'>{escape(summary or '')}"
                "</span></div>"
            )
    if not cards:
        cards = ["<p>No policies yet. Run <code>scripts/seed.py</code>.</p>"]
    return layout("critiSizer", f"<h1>critiSizer</h1>{''.join(cards)}")


@router.get("/policies/{slug}", response_class=HTMLResponse)
def policy_page(slug: str) -> HTMLResponse:
    with SessionLocal() as session:
        policy = session.scalar(select(Policy).where(Policy.slug == slug))
        if policy is None:
            raise HTTPException(status_code=404, detail="Policy not found")
        rubric = load_active_rubric(session)
        result = score_policy(session, policy.id, rubric)
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
                ev_html = ""
                for ev in ev_by_ind.get(ind.id, []):
                    excluded = ev.verification_multiplier == 0
                    css = "ev excluded" if excluded else "ev"
                    tag = " (excluded)" if excluded else ""
                    ev_html += (
                        f"<div class='{css}'>Tier {ev.source_tier}, "
                        f"x{ev.verification_multiplier}: "
                        f"<a href='{escape(ev.source_url)}'>"
                        f"{escape(ev.source_title)}</a>{tag}</div>"
                    )
                rows.append(
                    f"<div class='ind'><span class='score'>{ind.score:.0f}</span> "
                    f"{escape(ind.name)}"
                    f"<br><span class='note'>{escape(ind.description or '')}</span>"
                    f"{ev_html}</div>"
                )
            aspect_value = result.aspect_scores[aspect.code]
            sections.append(
                f"<div class='card'><h3>{escape(aspect.name)} "
                f"<span class='score'>{aspect_value:.1f}</span></h3>"
                f"{''.join(rows)}</div>"
            )

        if result.people_rating is not None:
            people = f"{result.people_rating:.1f} ({result.people_rating_count} ratings)"
        else:
            people = (
                f"not shown ({result.people_rating_count} ratings, "
                f"needs {rubric.min_ratings})"
            )
        spike = " &middot; <span class='spike'>Spike flag</span>" if result.spike_flag else ""
        summary_card = (
            f"<div class='card'><span class='score big'>{result.overall_rating:.1f}"
            f"</span> overall{spike}<br>Expert average {result.expert_average:.1f}"
            f" &middot; People's rating: {people}<br>"
            f"<span class='note'>Rubric {escape(result.rubric_label)}</span></div>"
        )

        body = (
            "<p><a href='/'>&larr; All policies</a></p>"
            f"<h1>{escape(policy.name)} ({policy.year})</h1>"
            f"<p>{escape(policy.summary or '')}</p>{summary_card}{''.join(sections)}"
        )
        title = policy.name
    return layout(title, body)