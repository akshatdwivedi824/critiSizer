"""HTML for the public pages. Pure: it takes the view objects that scorecard.py
builds and returns strings, so it can be tested without a database.

The hexagon is drawn on the server as SVG, so the pages need no script for it.
A higher value means more documented criticism. Only aspects on realised
evidence are in the shape that counts toward the rating. A projected aspect is
drawn as a dashed ring and a star, and is never part of the number.
"""

import math
from dataclasses import dataclass, field
from html import escape

from critisizer.schemas import (
    REVIEW_NOTE,
    AspectScoreOut,
    IndicatorOut,
    PolicyDetail,
)

SCOPE_NOTE = (
    "Scores are editorial and record negatives only; this is not a full "
    "evaluation of any policy. Higher means more documented criticism."
)
DISCLAIMER = f"{SCOPE_NOTE} {REVIEW_NOTE}."
NONE_FOUND = "No negative evidence found in the collected sources"

# Fixed order round the hexagon, clockwise from the top: (code, short label).
ORDER = (
    ("outcome_failure", "Outcome"),
    ("cost_waste", "Cost"),
    ("transparency_gap", "Transparency"),
    ("ground_level_harm", "Ground-level harm"),
    ("legal_challenges", "Legal"),
    ("equity_impact", "Equity"),
)
QUESTIONS = {
    "outcome_failure": "Did it fail to achieve what it set out to do?",
    "cost_waste": "What did it cost, and was money wasted?",
    "transparency_gap": "Was it developed and run in the open?",
    "ground_level_harm": "Who was hurt in practice?",
    "legal_challenges": "Did courts or the law push back?",
    "equity_impact": "Did the burden fall unevenly?",
}


@dataclass
class PageExtras:
    """Optional text that is not in the scoring data. Every field may be empty
    and the page then leaves that part out or falls back to what it has."""

    description: list[str] = field(default_factory=list)
    facts: list[tuple[str, str]] = field(default_factory=list)
    aims: list[tuple[str, str]] = field(default_factory=list)  # (text, source url)
    critique: list[str] = field(default_factory=list)
    aspect_summaries: dict[str, str] = field(default_factory=dict)
    summary_source_url: str | None = None


# ------------------------------------------------------------------ hexagon

CX, CY, R = 210, 190, 120


def _pos(index: int, value: float) -> tuple[float, float]:
    angle = -math.pi / 2 + index * math.pi / 3
    return CX + math.cos(angle) * R * value / 100, CY + math.sin(angle) * R * value / 100


def _pts(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def _value(aspect: AspectScoreOut | None) -> float | None:
    """Where an aspect sits on its axis, or None when it has no value."""
    if aspect is None:
        return None
    if aspect.status == "no_negative_evidence":
        return 0.0
    if aspect.status in ("scored", "projected"):
        return aspect.score
    return None


def hexagon_svg(aspects: list[AspectScoreOut], *, mini: bool = False) -> str:
    by_code = {a.code: a for a in aspects}
    found = [by_code.get(code) for code, _ in ORDER]
    values = [_value(a) for a in found]
    counted = [
        v if a is not None and a.status in ("scored", "no_negative_evidence") else None
        for a, v in zip(found, values, strict=True)
    ]

    out = []
    for level in (100, 75, 50, 25):
        css = "ring outer" if level == 100 else "ring"
        ring = _pts([_pos(i, level) for i in range(6)])
        out.append(f"<polygon points='{ring}' class='{css}'/>")

    # One shaded shape through all six corners: counted values, projected
    # values, and the 50 mark for aspects with no value. The dashed edge marks
    # the part that is not in the rating; solid segments sit on top of it.
    if sum(v is not None for v in counted) >= 3 or any(
        v is not None for v in values
    ) and sum(v is not None for v in values) >= 3:
        ring = _pts([_pos(i, v if v is not None else 50) for i, v in enumerate(values)])
        out.append(f"<polygon points='{ring}' class='proj-shape'/>")
    for i, v in enumerate(counted):
        nxt = counted[(i + 1) % 6]
        if v is not None and nxt is not None:
            (x1, y1), (x2, y2) = _pos(i, v), _pos((i + 1) % 6, nxt)
            out.append(
                f"<line x1='{x1:.1f}' y1='{y1:.1f}' x2='{x2:.1f}' y2='{y2:.1f}' "
                "class='seg'/>"
            )

    for i, (code, short) in enumerate(ORDER):
        aspect = by_code.get(code)
        status = aspect.status if aspect else "unresolved"
        value = values[i]
        name = escape(aspect.name if aspect else short)
        if status == "scored" and value is not None:
            x, y = _pos(i, value)
            out.append(
                f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{6 if mini else 5}' class='pt'>"
                f"<title>{name}: {value:.0f}</title></circle>"
            )
        elif mini:
            pass
        elif status == "no_negative_evidence":
            out.append(
                f"<circle cx='{CX}' cy='{CY}' r='5' class='pt-clear'>"
                f"<title>{name}: checked, no negative evidence found</title></circle>"
            )
        elif status == "projected" and value is not None:
            x, y = _pos(i, value)
            out.append(
                f"<circle cx='{x:.1f}' cy='{y:.1f}' r='6' class='pt-proj'>"
                f"<title>{name}: projected {value:.0f}, not in the rating</title>"
                "</circle>"
            )
            if not mini:
                out.append(
                    f"<text x='{x:.1f}' y='{y - 12:.1f}' text-anchor='middle' "
                    "class='star'>*</text>"
                )
        else:
            x, y = _pos(i, 50)
            out.append(
                f"<circle cx='{x:.1f}' cy='{y:.1f}' r='5' class='pt-open'>"
                f"<title>{name}: not assessed yet</title></circle>"
            )
        if not mini:
            lx, ly = _pos(i, 100)
            dx, dy = math.cos(-math.pi / 2 + i * math.pi / 3), math.sin(
                -math.pi / 2 + i * math.pi / 3
            )
            tx = lx + dx * 16
            ty = ly + dy * 16 + (10 if dy > 0.5 else -4 if dy < -0.5 else 4)
            anchor = "start" if dx > 0.3 else "end" if dx < -0.3 else "middle"
            out.append(
                f"<text x='{tx:.1f}' y='{ty:.1f}' text-anchor='{anchor}' "
                f"class='lab'>{escape(short)}</text>"
            )

    box = "80 60 260 260" if mini else "0 0 420 380"
    css = "hex mini" if mini else "hex"
    return (
        f"<svg class='{css}' viewBox='{box}' role='img' "
        "aria-label='Hexagon of six aspects, one axis each'>"
        f"{''.join(out)}</svg>"
    )


# ------------------------------------------------------------------ pieces


def _href(url: str) -> str:
    return escape(url) if url.lower().startswith(("http://", "https://")) else "#"


def _evidence_html(indicator: IndicatorOut) -> str:
    out = []
    for ev in indicator.evidence:
        css = "excluded" if ev.excluded else ""
        quote = f"&ldquo;{escape(ev.quote)}&rdquo;" if ev.quote else ""
        outlet = f" &middot; {escape(ev.outlet)}" if ev.outlet else ""
        tag = " (excluded)" if ev.excluded else ""
        out.append(
            f"<blockquote class='{css}'>{quote}<cite>"
            f"<a href='{_href(ev.source_url)}' rel='noopener'>"
            f"{escape(ev.source_title)}</a>{outlet}{tag}</cite></blockquote>"
        )
    return "".join(out)


def _indicator_html(ind: IndicatorOut, *, projected: bool) -> str:
    head = f"<h4>{escape(ind.name)}"
    if not projected:
        head += f"<span>{ind.score:.0f}</span>"
    head += "</h4>"
    desc = f"<p>{escape(ind.description)}</p>" if ind.description else ""
    basis = ""
    if projected and ind.projection_source:
        basis = f"<p>The basis is {escape(ind.projection_source)}.</p>"
    return f"<div class='ind'>{head}{desc}{basis}{_evidence_html(ind)}</div>"


def _badge(aspect: AspectScoreOut) -> str:
    if aspect.status == "scored" and aspect.score is not None:
        return f"<div class='badge'>{aspect.score:.0f}</div>"
    if aspect.status == "no_negative_evidence":
        return "<div class='badge clear'>0</div>"
    if aspect.status == "projected" and aspect.score is not None:
        return f"<div class='badge dim'>{aspect.score:.0f}<sup>&#9733;</sup></div>"
    return "<div class='badge dim'>&ndash;</div>"


def _aspect_body(aspect: AspectScoreOut, summary: str | None) -> str:
    parts = []
    if summary:
        parts.append(f"<p class='why'>{escape(summary)}</p>")
    if aspect.status in ("scored", "projected"):
        parts.extend(
            _indicator_html(ind, projected=aspect.status == "projected")
            for ind in aspect.indicators
        )
    elif aspect.status == "no_negative_evidence":
        parts.append(f"<p class='why'>{NONE_FOUND}.</p>")
        if aspect.review_reason:
            parts.append(
                f"<p class='reason'>Reviewer note: {escape(aspect.review_reason)}</p>"
            )
    elif aspect.status == "too_early":
        if aspect.review_reason:
            parts.append(f"<p class='reason'>{escape(aspect.review_reason)}</p>")
        if aspect.review_date:
            parts.append(
                f"<p class='reason'>Look again: {aspect.review_date:%B %Y}.</p>"
            )
    else:
        parts.append("<p class='reason'>Not assessed yet.</p>")
    return "".join(parts)


def aspect_card(aspect: AspectScoreOut, summary: str | None = None) -> str:
    question = QUESTIONS.get(aspect.code, "")
    return (
        "<details class='aspect' open>"
        f"<summary><h3>{escape(aspect.name)}</h3>"
        f"<span class='q'>{escape(question)}</span>{_badge(aspect)}"
        "<span class='chev' aria-hidden='true'></span></summary>"
        f"<div class='body'>{_aspect_body(aspect, summary)}</div></details>"
    )


def _aspect_sort_key(aspect: AspectScoreOut) -> tuple[int, int]:
    rank = {
        "scored": 0,
        "no_negative_evidence": 1,
        "projected": 2,
        "too_early": 3,
        "unresolved": 4,
    }
    order = [code for code, _ in ORDER]
    index = order.index(aspect.code) if aspect.code in order else len(order)
    return rank.get(aspect.status, 5), index


def critique_html(view: PolicyDetail, extras: PageExtras) -> str:
    """The short overall critique. Written text when there is some; otherwise
    built from the reviewed findings, so it never says more than they do."""
    if extras.critique:
        body = "".join(f"<p>{escape(p)}</p>" for p in extras.critique)
        return body
    scored = [a for a in view.aspects if a.status == "scored" and a.score is not None]
    if not scored:
        return "<p>Nothing has been scored for this policy yet.</p>"
    rows = []
    for aspect in sorted(scored, key=lambda a: -(a.score or 0)):
        top = max(aspect.indicators, key=lambda i: i.score, default=None)
        text = ""
        if top is not None:
            text = top.description or top.name
        rows.append(
            f"<p><strong>{escape(aspect.name)} &middot; {aspect.score:.0f}.</strong> "
            f"{escape(text)}</p>"
        )
    return "".join(rows)


def _facts_html(view: PolicyDetail, extras: PageExtras) -> str:
    """Key facts: the written ones when there are any, else what is on record."""
    rows = [(escape(k), escape(v)) for k, v in extras.facts]
    if not rows:
        rows = [("Year", str(view.year))]
        if extras.summary_source_url:
            link = (
                f"<a href='{_href(extras.summary_source_url)}' rel='noopener'>"
                "Read the source</a>"
            )
            rows.append(("Source of this summary", link))
    return "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows)


# ------------------------------------------------------------------ layout

CSS = """
:root {
  --bg: #0f1115; --surface: #171a21; --line: #2a2f3a; --fg: #e8eaee;
  --muted: #9aa3b2; --accent: #3fbf9a; --accent-soft: rgba(63, 191, 154, 0.22);
  --shape: rgba(63, 191, 154, 0.40); --clear: #6cb4ee;
  --head: "Space Grotesk", system-ui, sans-serif;
  --body: "Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  color-scheme: dark;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg: #f4f5f7; --surface: #ffffff; --line: #d9dde4; --fg: #14171c;
    --muted: #5b6575; --accent: #1f8f6b; --accent-soft: rgba(31, 143, 107, 0.16);
    --shape: rgba(31, 143, 107, 0.28); --clear: #1b6fb5; color-scheme: light;
  }
}
:root[data-theme="light"] {
  --bg: #f4f5f7; --surface: #ffffff; --line: #d9dde4; --fg: #14171c;
  --muted: #5b6575; --accent: #1f8f6b; --accent-soft: rgba(31, 143, 107, 0.16);
  --shape: rgba(31, 143, 107, 0.28); --clear: #1b6fb5; color-scheme: light;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font-family: var(--body); font-size: 15px; line-height: 1.6;
}
a { color: inherit; }
h1, h2, h3, h4 { font-family: var(--head); line-height: 1.15; margin: 0; }
.wrap { max-width: 1040px; margin: 0 auto; padding: 24px 16px 56px;
  display: grid; gap: 28px; }
.site { display: flex; justify-content: space-between; align-items: center;
  gap: 12px; color: var(--muted); font-size: 13px; }
.site a { text-decoration: none; }
.site .brand { font-family: var(--head); font-weight: 700; font-size: 16px;
  color: var(--fg); }
button { background: var(--surface); color: var(--fg); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 10px; font: inherit; font-size: 13px;
  cursor: pointer; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.head { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px;
  align-items: center; }
.head h1 { font-size: clamp(30px, 5vw, 44px); }
.head .yr { color: var(--muted); font-weight: 500; }
.head p { color: var(--muted); max-width: 65ch; margin: 10px 0 0; }
.minibox { display: grid; justify-items: center; gap: 2px; }
.miniscore { font-family: var(--head); font-weight: 700; font-size: 28px;
  line-height: 1; font-variant-numeric: tabular-nums; }
.miniscore.none { font-size: 14px; font-weight: 500; color: var(--muted); }
svg.hex.mini { width: 150px; height: 150px; }
@media (max-width: 520px) { svg.hex.mini { width: 100px; height: 100px; } }
.card { background: var(--surface); border: 1px solid var(--line);
  border-radius: 12px; padding: 20px; }
.card h2 { font-size: 22px; margin-bottom: 10px; }
.nutshell { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: 28px; }
.nutshell p { margin: 0 0 12px; max-width: 65ch; }
.card.nutshell { background: none; border: 0; border-radius: 0; position: relative;
  padding: 0; margin: 0 4px; gap: 0;
  --ext: max(0px, min(160px, calc((100vw - 100%) / 2 - 24px))); }
.card.nutshell::before, .card.nutshell::after { content: ""; position: absolute;
  left: calc(-1 * var(--ext)); right: calc(-1 * var(--ext)); height: 1px;
  background: var(--line); pointer-events: none; }
.card.nutshell::before { top: 0; }
.card.nutshell::after { bottom: 0; }
.card.nutshell > div { padding: 22px 28px 22px 0; }
.card.nutshell > .facts { padding: 22px 0 22px 28px;
  border-left: 1px solid var(--line); }
.card.nutshell .facts div:first-child { border-top: 0; padding-top: 0; }
.facts { margin: 0; display: grid; gap: 12px; align-content: start; font-size: 14px; }
.facts div { border-top: 1px solid var(--line); padding-top: 8px; }
.facts dt { color: var(--muted); font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.06em; }
.facts dd { margin: 2px 0 0; }
.top { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0; align-items: stretch; }
.top > .card { background: none; border: 0; border-radius: 0;
  padding: 20px 28px 20px 0; }
.top > .card + .card { border-left: 1px solid var(--line); padding: 20px 0 20px 28px; }
@media (max-width: 760px) {
  .top, .nutshell { grid-template-columns: minmax(0, 1fr); }
  .top > .card { padding-right: 0; }
  .card.nutshell > div { padding-right: 0; }
  .card.nutshell > .facts { border-left: 0; border-top: 1px solid var(--line);
    padding: 22px 0; }
  .top > .card + .card { border-left: 0; border-top: 1px solid var(--line);
    padding: 20px 0 0; }
}
.score .num { font-family: var(--head); font-weight: 700; font-size: 64px;
  line-height: 1; font-variant-numeric: tabular-nums; }
.score .num.none { font-size: 28px; color: var(--muted); font-weight: 500; }
.need { color: var(--muted); font-size: 13px; margin: 8px 0 0; }
.meter { margin-top: 14px; height: 6px; border-radius: 3px; background: var(--line);
  overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--accent); }
.scale { display: flex; justify-content: space-between; color: var(--muted);
  font-size: 12px; margin-top: 6px; }
svg.hex { width: 100%; height: auto; display: block; }
svg.hex text { font-family: var(--body); fill: var(--fg); font-size: 12.5px;
  font-weight: 500; }
.ring { fill: none; stroke: var(--line); stroke-width: 1; }
.proj-shape { fill: var(--shape); stroke: var(--accent); stroke-width: 1.6;
  stroke-dasharray: 5 4; stroke-linejoin: round; }
.shape { fill: var(--shape); stroke: none; }
.shape.hollow { fill: none; }
.seg { stroke: var(--accent); stroke-width: 2.2; stroke-linecap: round; }
.seg-open { stroke: var(--accent); stroke-width: 1.6; stroke-dasharray: 4 4;
  stroke-linecap: round; opacity: .8; }
svg.hex text.star { fill: var(--accent); font-size: 20px; font-weight: 700; }
.mini .seg { stroke-width: 4; }
.mini .proj-shape { stroke-width: 3; }
.mini .ring { stroke-width: 1.5; }
.pt { fill: var(--accent); }
.pt-clear { fill: var(--bg); stroke: var(--clear); stroke-width: 2.2; }
.pt-open { fill: var(--bg); stroke: var(--muted); stroke-width: 1.6;
  stroke-dasharray: 3 3; }
.pt-proj { fill: none; stroke: var(--accent); stroke-width: 2;
  stroke-dasharray: 3 3; }
.critique p { margin: 0 0 12px; max-width: 65ch; }
.note { color: var(--muted); font-size: 13px; margin: 0; }
.sect-h { font-size: 22px; }
.aspects { display: grid; gap: 0; grid-template-columns: minmax(0, 1fr);
  border-top: 1px solid var(--line); }
.aspects .starnote { grid-column: 1 / -1; }
.starnote { color: var(--muted); font-size: 12.5px; margin: 8px 16px 0; }
.aspect { border-bottom: 1px solid var(--line); }
.aspect > summary { list-style: none; cursor: pointer; padding: 14px 16px;
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 4px 14px;
  align-items: center; }
.aspect > summary::-webkit-details-marker { display: none; }
.chev { grid-row: 1 / span 2; grid-column: 1; justify-self: center; width: 9px;
  height: 9px; border-right: 2px solid var(--muted);
  border-bottom: 2px solid var(--muted); transform: translate(0, -3px) rotate(45deg);
  transition: transform 0.18s ease, border-color 0.18s ease; }
.aspect:not([open]) .chev { transform: translate(-2px, 0) rotate(-45deg); }
.aspect > summary:hover .chev { border-color: var(--accent); }
.aspect h3 { font-size: 17px; grid-column: 2; }
.aspect .q { color: var(--muted); font-size: 13px; grid-column: 2; }
.badge { font-family: var(--head); font-weight: 700; font-size: 22px;
  font-variant-numeric: tabular-nums; grid-row: 1 / span 2; grid-column: 3;
  text-align: right; }
.badge.dim { color: var(--muted); }
.badge.clear { color: var(--clear); }
.badge sup { font-size: 13px; margin-left: 2px; }
.body { padding: 0 16px 16px; display: grid; gap: 14px; }
.why { margin: 0; font-size: 14.5px; }
.reason { margin: 0; color: var(--muted); font-size: 14px; }
.ind { border-top: 1px solid var(--line); padding-top: 12px; display: grid; gap: 6px; }
.ind h4 { font-size: 15px; font-weight: 600; display: flex;
  justify-content: space-between; gap: 12px; }
.ind h4 span { color: var(--muted); font-variant-numeric: tabular-nums;
  font-weight: 500; }
.ind p { margin: 0; color: var(--muted); font-size: 14px; }
blockquote { margin: 0; padding-left: 12px; border-left: 2px solid var(--line);
  font-size: 13.5px; }
blockquote.excluded { text-decoration: line-through; opacity: 0.6; }
blockquote cite { display: block; font-style: normal; color: var(--muted);
  font-size: 12px; margin-top: 2px; }
.aims { margin: 0; padding-left: 18px; display: grid; gap: 14px; }
.aims a { color: var(--muted); font-size: 13px; }
.foot { color: var(--muted); font-size: 13px; border-top: 1px solid var(--line);
  padding-top: 16px; display: flex; gap: 8px 24px; flex-wrap: wrap; }
.tag { border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; }
.search { width: 100%; max-width: 420px; background: var(--surface);
  color: var(--fg); border: 1px solid var(--line); border-radius: 8px;
  padding: 10px 12px; font: inherit; }
.intro h1 { font-size: clamp(30px, 5vw, 44px); }
.intro p { color: var(--muted); max-width: 65ch; margin: 10px 0 14px; }
.plist { display: grid; gap: 12px; }
.pcard { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 16px;
  align-items: center; padding: 10px 0; text-decoration: none; color: var(--fg);
  transition: color 0.18s ease; }
.pcard:hover, .pcard:focus-visible { color: var(--accent); }
.pcard svg.hex.mini { width: 84px; height: 84px; }
.pcard h3 { font-size: 18px; }
.pcard h3 span { color: inherit; font-weight: 500; }
.pcard p { margin: 4px 0 0; color: inherit; font-size: 14px; }
.pcard .pscore small { color: inherit; }
.pscore { text-align: right; font-family: var(--head); font-weight: 700;
  font-size: 30px; font-variant-numeric: tabular-nums; }
.pscore small { display: block; font-family: var(--body); font-weight: 400;
  font-size: 12px; color: var(--muted); }
.group-h { font-size: 15px; color: var(--muted); font-weight: 500;
  margin: 8px 0 10px; }
@media (max-width: 520px) {
  .pcard { grid-template-columns: auto minmax(0, 1fr); }
  .pscore { grid-column: 1 / -1; text-align: left; }
}
"""

HEAD_SCRIPT = (
    "try{var t=localStorage.getItem('theme');"
    "if(t)document.documentElement.dataset.theme=t}catch(e){}"
)
THEME_SCRIPT = """
(function () {
  var btn = document.getElementById('theme');
  if (!btn) return;
  var root = document.documentElement;
  function now() {
    return root.dataset.theme ||
      (window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches
        ? 'light' : 'dark');
  }
  function label() { btn.textContent = now() === 'dark' ? 'Light mode' : 'Dark mode'; }
  btn.addEventListener('click', function () {
    var next = now() === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('theme', next); } catch (e) {}
    label();
  });
  label();
})();
"""
SEARCH_SCRIPT = """
(function () {
  var q = document.getElementById('q');
  if (!q) return;
  var items = [].slice.call(document.querySelectorAll('.pcard'));
  var groups = [].slice.call(document.querySelectorAll('[data-group]'));
  var none = document.getElementById('none');
  function run() {
    var t = q.value.trim().toLowerCase(), shown = 0;
    items.forEach(function (el) {
      var ok = !t || el.dataset.text.indexOf(t) !== -1;
      el.hidden = !ok;
      if (ok) shown++;
    });
    groups.forEach(function (g) { g.hidden = !g.querySelector('.pcard:not([hidden])'); });
    none.hidden = shown !== 0;
  }
  q.addEventListener('input', run);
})();
"""


def layout(title: str, body: str, *, search: bool = False) -> str:
    script = THEME_SCRIPT + (SEARCH_SCRIPT if search else "")
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta name='color-scheme' content='dark light'>"
        f"<title>{escape(title)}</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?"
        "family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;700"
        "&display=swap'>"
        f"<script>{HEAD_SCRIPT}</script><style>{CSS}</style></head><body>"
        "<div class='wrap'><div class='site'>"
        "<a class='brand' href='/'>critiSizer</a>"
        "<button id='theme' type='button'>Light mode</button></div>"
        f"{body}</div><script>{script}</script></body></html>"
    )


# ------------------------------------------------------------------ pages


def _footer(view: PolicyDetail) -> str:
    """Just the scope note. The tags, aspect count, source depth, people's
    rating line and the AI-drafted note are not shown on the policy page."""
    return f"<footer class='foot'><span>{escape(SCOPE_NOTE)}</span></footer>"


def policy_html(view: PolicyDetail, extras: PageExtras, needed: int) -> str:
    """Body of a policy page. `needed` is how many assessed aspects a rating takes."""
    rated = view.rated and view.overall_rating is not None
    mini_score = (
        f"<div class='miniscore'>{view.overall_rating:.1f}</div>"
        if rated
        else "<div class='miniscore none'>Not yet rated</div>"
    )
    head = (
        "<header class='head'><div>"
        f"<h1>{escape(view.name)} <span class='yr'>({view.year})</span></h1>"
        f"<p>{escape(view.summary or '')}</p></div>"
        f"<div class='minibox'>{hexagon_svg(view.aspects, mini=True)}"
        f"{mini_score}</div></header>"
    )

    paragraphs = extras.description or ([view.summary] if view.summary else [])
    nutshell = (
        "<section class='card nutshell'><div><h2>The policy: In a nutshell</h2>"
        f"{''.join(f'<p>{escape(p)}</p>' for p in paragraphs)}</div>"
        f"<dl class='facts'>{_facts_html(view, extras)}</dl></section>"
    )

    if rated:
        score = (
            f"<div class='score'><span class='num'>{view.overall_rating:.1f}</span>"
            "</div><div class='meter' aria-hidden='true'>"
            f"<i style='width:{view.overall_rating:.1f}%'></i></div>"
            "<div class='scale'><span>0 &middot; little documented criticism</span>"
            "<span>100 &middot; a lot</span></div>"
        )
    elif view.scored:
        score = (
            "<div class='score'><span class='num none'>Not yet rated</span></div>"
            f"<p class='need'>A rating needs {needed} aspects assessed on documented "
            f"evidence. {view.aspects_assessed} so far.</p>"
        )
    else:
        score = (
            "<div class='score'><span class='num none'>Not yet scored</span></div>"
            "<p class='need'>Scores appear here once documented evidence has been "
            "collected and reviewed.</p>"
        )
    top = (
        "<section class='top'><div class='card'>"
        f"{score}{hexagon_svg(view.aspects)}</div>"
        "<div class='card critique'><h2>A brief critique</h2>"
        f"{critique_html(view, extras)}"
        "<p class='note'>Built only from the reviewed findings below.</p></div>"
        "</section>"
    )

    cards = ""
    if view.aspects:
        ordered = sorted(view.aspects, key=_aspect_sort_key)
        cards = "".join(
            aspect_card(a, extras.aspect_summaries.get(a.code)) for a in ordered
        )
        if any(a.status == "projected" for a in view.aspects):
            cards += (
                "<p class='starnote'>&#9733; Projected value. "
                "The basis is stated in its box.</p>"
            )
        cards = (
            "<h2 class='sect-h'>Description</h2>"
            f"<section class='aspects'>{cards}</section>"
        )

    other = ""
    if extras.aims:
        items = "".join(
            f"<li>{escape(text)} <a href='{_href(url)}' rel='noopener'>Source</a></li>"
            for text, url in extras.aims
        )
        other = (
            "<section class='card'><h2>The other side</h2>"
            "<p class='note'>What the government said the policy was for. Shown "
            f"for context and not scored.</p><ul class='aims'>{items}</ul></section>"
        )

    crumb = (
        "<p class='note'><a href='/'>&larr; All policies</a></p>"
    )
    return f"{crumb}{head}{nutshell}{top}{cards}{other}{_footer(view)}"


def home_html(views: list[PolicyDetail], needed: int) -> str:
    rated = sorted(
        (v for v in views if v.rated and v.overall_rating is not None),
        key=lambda v: (-(v.overall_rating or 0), v.name),
    )
    rest = sorted(
        (v for v in views if not (v.rated and v.overall_rating is not None)),
        key=lambda v: (-v.aspects_assessed, v.name),
    )

    def card(view: PolicyDetail) -> str:
        if view.rated and view.overall_rating is not None:
            score = f"<div class='pscore'>{view.overall_rating:.1f}</div>"
        elif view.scored:
            score = (
                "<div class='pscore'><small>Not yet rated<br>"
                f"{view.aspects_assessed} of {needed} aspects</small></div>"
            )
        else:
            score = "<div class='pscore'><small>Not yet scored</small></div>"
        text = escape(f"{view.name} {view.year} {view.summary or ''}".lower())
        return (
            f"<a class='pcard' href='/policies/{escape(view.slug)}' "
            f"data-text='{text}'>{hexagon_svg(view.aspects, mini=True)}"
            f"<div><h3>{escape(view.name)} <span>({view.year})</span></h3>"
            f"<p>{escape(view.summary or '')}</p></div>{score}</a>"
        )

    def group(title: str, items: list[PolicyDetail], key: str) -> str:
        if not items:
            return ""
        return (
            f"<section data-group='{key}'><h2 class='group-h'>{title}</h2>"
            f"<div class='plist'>{''.join(card(v) for v in items)}</div></section>"
        )

    if not views:
        listing = "<p>No policies yet. Run <code>scripts/seed.py</code>.</p>"
    else:
        listing = (
            group("Rated", rated, "rated")
            + group("Not yet rated", rest, "rest")
            + "<p id='none' hidden>No policy matches that search.</p>"
        )
    intro = (
        "<header class='intro'><h1>critiSizer</h1>"
        "<p>A scorecard of documented criticism of Indian government policies. "
        "A higher score means more documented criticism, from named sources.</p>"
        "<input id='q' class='search' type='search' autocomplete='off' "
        "placeholder='Search policies' aria-label='Search policies'></header>"
    )
    foot = f"<footer class='foot'><span>{escape(DISCLAIMER)}</span></footer>"
    return f"{intro}{listing}{foot}"