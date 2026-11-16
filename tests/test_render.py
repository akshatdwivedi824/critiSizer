"""Rendering tests that need no database: they build the view objects directly."""

from datetime import date

from critisizer.render import (
    PageExtras,
    _href,
    critique_html,
    hexagon_svg,
    home_html,
    layout,
    policy_html,
)
from critisizer.schemas import AspectScoreOut, EvidenceOut, IndicatorOut, PolicyDetail

CODES = [
    "outcome_failure",
    "cost_waste",
    "transparency_gap",
    "ground_level_harm",
    "legal_challenges",
    "equity_impact",
]


def evidence(quote="A quote.", excluded=False):
    return EvidenceOut(
        source_url="https://example.org/a",
        source_title="A title",
        source_tier=2,
        multiplier=0.0 if excluded else 1.0,
        excluded=excluded,
        quote=quote,
        outlet="The Wire",
    )


def indicator(score=60.0, description="What went wrong.", **kw):
    return IndicatorOut(
        name="An indicator",
        description=description,
        score=score,
        weight=1.0,
        evidence=[evidence()],
        **kw,
    )


def aspect(code, status="scored", score=60.0, indicators=None, **kw):
    return AspectScoreOut(
        code=code,
        name=code.replace("_", " ").title(),
        score=score,
        status=status,
        indicators=[indicator(score or 0)] if indicators is None else indicators,
        **kw,
    )


def all_scored(score=60.0):
    return [aspect(code, score=score) for code in CODES]


def policy(aspects, *, rated=True, rating=55.4, **kw):
    fields = {
        "slug": "p",
        "name": "A policy",
        "year": 2020,
        "summary": "A short summary.",
        "scored": bool(aspects),
        "rated": rated,
        "aspects_resolved": len(aspects),
        "aspects_assessed": len(aspects),
        "aspects_total": 6,
        "overall_rating": rating if rated else None,
        "spike_flag": True,
        "people_rating": None,
        "people_rating_count": 0,
        "people_rating_visible": False,
        "rubric_label": "v1",
        "expert_average": None,
        "aspects": aspects,
        "source_count": 5,
        "outlet_count": 2,
    }
    fields.update(kw)
    return PolicyDetail(**fields)


# ---------------------------------------------------------------- hexagon


def test_each_state_gets_its_own_marker():
    aspects = [
        aspect("outcome_failure"),
        aspect("cost_waste", "no_negative_evidence", 0.0, []),
        aspect("transparency_gap", "projected", 70.0, []),
        aspect("ground_level_harm", "too_early", None, []),
        aspect("legal_challenges", "unresolved", None, []),
    ]
    svg = hexagon_svg(aspects)
    assert svg.count("class='pt'") == 1
    assert svg.count("class='pt-clear'") == 1
    assert svg.count("class='pt-proj'") == 1
    # too early, unresolved and the missing sixth aspect are open rings
    assert svg.count("class='pt-open'") == 3


def test_the_shaded_shape_needs_three_values_and_is_closed_by_placeholders():
    assert "proj-shape" not in hexagon_svg([aspect(code) for code in CODES[:2]])
    four = [aspect(code) for code in CODES[:4]]
    svg = hexagon_svg(four)
    assert svg.count("class='proj-shape'") == 1
    assert svg.count("class='seg'") == 3


def test_a_projected_value_is_not_part_of_the_solid_outline():
    aspects = [aspect(code) for code in CODES[:5]]
    aspects.append(aspect(CODES[5], "projected", 90.0, []))
    svg = hexagon_svg(aspects)
    # five counted corners in a ring give four neighbouring segments
    assert svg.count("class='seg'") == 4


def test_the_miniature_has_no_labels_and_no_open_rings():
    svg = hexagon_svg(all_scored()[:3], mini=True)
    assert "class='lab'" not in svg
    assert "pt-open" not in svg
    assert "hex mini" in svg


def test_an_empty_policy_still_draws_a_hexagon():
    svg = hexagon_svg([])
    assert svg.count("class='pt-open'") == 6
    assert "class='shape" not in svg


# ---------------------------------------------------------------- policy page


def test_rated_page_shows_the_score_and_hides_the_spike_flag():
    html = policy_html(policy(all_scored()), PageExtras(), 4)
    assert "55.4" in html
    assert "Not yet rated" not in html
    assert "SPIKE" not in html.upper().replace("SPIKE-", "")


def test_unrated_page_says_how_many_are_needed():
    aspects = [aspect(code) for code in CODES[:3]]
    html = policy_html(policy(aspects, rated=False), PageExtras(), 4)
    assert "Not yet rated" in html
    assert "needs 4 aspects" in html
    assert "3 so far" in html
    assert "class='meter'" not in html


def test_unscored_page_says_so():
    html = policy_html(policy([], rated=False, scored=False), PageExtras(), 4)
    assert "Not yet scored" in html


def test_quotes_titles_and_names_are_escaped():
    bad = IndicatorOut(
        name="<i>name</i>",
        description="<u>d</u>",
        score=50.0,
        weight=1.0,
        evidence=[evidence(quote="<b>x</b>")],
    )
    aspects = [aspect("outcome_failure", indicators=[bad])]
    view = policy(aspects, rated=False, name="<script>alert(1)</script>")
    html = policy_html(view, PageExtras(), 4)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "<b>x</b>" not in html
    assert "<i>name</i>" not in html


def test_only_web_links_are_used_as_hrefs():
    assert _href("https://a.org/x") == "https://a.org/x"
    assert _href("javascript:alert(1)") == "#"


def test_excluded_evidence_is_marked():
    ind = IndicatorOut(
        name="n",
        description=None,
        score=10.0,
        weight=1.0,
        evidence=[evidence(excluded=True)],
    )
    html = policy_html(
        policy([aspect("outcome_failure", indicators=[ind])], rated=False),
        PageExtras(),
        4,
    )
    assert "(excluded)" in html


def test_projected_aspect_shows_a_star_the_basis_and_the_footnote():
    proj = indicator(
        70.0, evidence_status="projected", projection_source="a named forecast"
    )
    aspects = [aspect("outcome_failure", "projected", 70.0, [proj])]
    html = policy_html(policy(aspects, rated=False), PageExtras(), 4)
    assert "&#9733;" in html
    assert "The basis is a named forecast." in html
    assert "Projected value." in html


def test_no_footnote_without_a_projected_aspect():
    html = policy_html(policy(all_scored()), PageExtras(), 4)
    assert "Projected value." not in html


def test_too_early_shows_the_reason_and_the_date():
    aspects = [
        aspect(
            "legal_challenges",
            "too_early",
            None,
            [],
            review_reason="Case still being argued.",
            review_date=date(2027, 6, 1),
        )
    ]
    html = policy_html(policy(aspects, rated=False), PageExtras(), 4)
    assert "Case still being argued." in html
    assert "Look again: June 2027." in html


def test_no_negative_evidence_shows_its_label_and_note():
    aspects = [
        aspect(
            "cost_waste",
            "no_negative_evidence",
            0.0,
            [],
            review_reason="read every source",
        )
    ]
    html = policy_html(policy(aspects, rated=False), PageExtras(), 4)
    assert "No negative evidence found in the collected sources" in html
    assert "Reviewer note: read every source" in html


def test_scored_aspects_come_first_in_the_list():
    aspects = [
        aspect("outcome_failure", "unresolved", None, []),
        aspect("cost_waste"),
    ]
    html = policy_html(policy(aspects, rated=False), PageExtras(), 4)
    assert html.index("Cost Waste") < html.index("Outcome Failure")


def test_other_side_is_left_out_without_aims_and_listed_with_them():
    view = policy(all_scored())
    assert "The other side" not in policy_html(view, PageExtras(), 4)
    extras = PageExtras(aims=[("Stop black money", "https://example.org/s")])
    html = policy_html(view, extras, 4)
    assert "The other side" in html
    assert "Stop black money" in html


def test_summary_is_the_description_until_a_longer_one_exists():
    view = policy(all_scored())
    assert "A short summary." in policy_html(view, PageExtras(), 4)
    html = policy_html(view, PageExtras(description=["Long text."]), 4)
    assert "Long text." in html


def test_fallback_critique_uses_the_reviewed_descriptions_highest_first():
    aspects = [
        aspect("outcome_failure", score=40.0, indicators=[indicator(40, "Low one.")]),
        aspect("cost_waste", score=80.0, indicators=[indicator(80, "High one.")]),
    ]
    html = critique_html(policy(aspects, rated=False), PageExtras())
    assert html.index("High one.") < html.index("Low one.")


def test_written_critique_replaces_the_fallback():
    html = critique_html(policy(all_scored()), PageExtras(critique=["Written."]))
    assert "Written." in html
    assert "What went wrong." not in html


# ---------------------------------------------------------------- home page


def test_home_lists_rated_policies_first_by_rating():
    low = policy(all_scored(), rating=30.0, slug="low", name="Low")
    high = policy(all_scored(), rating=70.0, slug="high", name="High")
    unrated = policy([aspect("outcome_failure")], rated=False, slug="u", name="Unrated")
    html = home_html([unrated, low, high], 4)
    assert html.index("High") < html.index("Low") < html.index("Unrated")
    assert "1 of 4 aspects" in html


def test_home_has_a_search_box_and_carries_the_disclaimer():
    html = home_html([policy(all_scored())], 4)
    assert "id='q'" in html
    assert "AI-drafted, human-reviewed" in html


def test_home_with_no_policies_says_so():
    assert "No policies yet" in home_html([], 4)


def test_layout_escapes_the_title_and_loads_no_third_party_script():
    html = layout("<x>", "<p>body</p>")
    assert "&lt;x&gt;" in html
    assert "<script src" not in html