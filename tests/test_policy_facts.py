"""The hand-written key facts must exist for every policy and say who decided."""

from critisizer.web import _all_facts

SLUGS = [
    "demonetisation-2016",
    "gst-rollout-2017",
    "farm-laws-2020",
    "electoral-bonds-scheme-2018",
    "dpdp-act-2023",
    "telecommunications-act-2023",
    "agnipath-scheme-2022",
    "spectrum-allocation-2g-2008",
]


def test_every_policy_has_facts_with_a_decider_and_a_status():
    facts = _all_facts()
    for slug in SLUGS:
        labels = [label for label, _ in facts.get(slug, [])]
        assert "Decided by" in labels, slug
        assert "Status" in labels, slug


def test_the_facts_page_renders_them(client, session):
    from critisizer.models import Policy

    session.add(
        Policy(slug="demonetisation-2016", name="Demonetisation", year=2016, summary="s")
    )
    session.commit()
    html = client.get("/policies/demonetisation-2016").text
    assert "Decided by" in html
    assert "BJP" in html