from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from critisizer.deps import SessionDep
from critisizer.models import Policy, PolicyAim
from critisizer.render import PageExtras, home_html, layout, policy_html
from critisizer.scorecard import (
    MIN_ASSESSED,
    build_policy_detail,
    load_active_rubric,
)
from critisizer.scoring.engine import Rubric

router = APIRouter()

FACTS_FILE = Path("seed/policy_facts.yaml")


@lru_cache(maxsize=1)
def _all_facts() -> dict[str, list[tuple[str, str]]]:
    """Key facts per policy, written by hand in seed/policy_facts.yaml. A missing
    or unreadable file means the page falls back to the year alone."""
    for base in (Path.cwd(), Path(__file__).resolve().parents[2]):
        path = base / FACTS_FILE
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return {}
        out: dict[str, list[tuple[str, str]]] = {}
        for slug, rows in (data.get("policies") or {}).items():
            if isinstance(rows, dict):
                out[str(slug)] = [
                    (str(k), str(v)) for k, v in rows.items() if v is not None
                ]
        return out
    return {}


def _rubric(session: Session) -> Rubric:
    """The active rubric. Without one, unrated pages still render."""
    try:
        return load_active_rubric(session)
    except LookupError:
        return Rubric(label="none", weights={}, min_ratings=0)


def _extras(session: Session, policy: Policy) -> PageExtras:
    """Text for the page that is not scoring data. Today that is the approved
    stated aims; the longer description, key facts and written critique join
    here once they are stored."""
    aims = session.scalars(
        select(PolicyAim)
        .where(PolicyAim.policy_id == policy.id, PolicyAim.status == "approved")
        .order_by(PolicyAim.position, PolicyAim.id)
    ).all()
    return PageExtras(
        facts=_all_facts().get(policy.slug, []),
        aims=[(a.text, a.source_url) for a in aims],
        summary_source_url=policy.summary_source_url,
    )


@router.get("/", response_class=HTMLResponse)
def index(session: SessionDep) -> HTMLResponse:
    policies = session.scalars(select(Policy).order_by(Policy.name)).all()
    rubric = _rubric(session)
    views = [build_policy_detail(session, p, rubric) for p in policies]
    needed = min(MIN_ASSESSED, views[0].aspects_total) if views else MIN_ASSESSED
    return HTMLResponse(layout("critiSizer", home_html(views, needed), search=True))


@router.get("/policies/{slug}", response_class=HTMLResponse)
def policy_page(slug: str, session: SessionDep) -> HTMLResponse:
    policy = session.scalar(select(Policy).where(Policy.slug == slug))
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found")
    view = build_policy_detail(session, policy, _rubric(session))
    needed = min(MIN_ASSESSED, view.aspects_total)
    body = policy_html(view, _extras(session, policy), needed)
    return HTMLResponse(layout(view.name, body))