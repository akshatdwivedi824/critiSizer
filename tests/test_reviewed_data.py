import copy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select

from critisizer.models import (
    Aspect,
    AspectReview,
    Evidence,
    EvidenceRun,
    Indicator,
    Policy,
    PolicyAim,
    SourceItem,
)
from critisizer.reviewed_data import export_reviewed, import_reviewed

SLUG = "rd-test-policy"


def _aspect(session, code):
    row = session.scalar(select(Aspect).where(Aspect.code == code))
    if row is None:
        row = Aspect(code=code, name=code, definition="test")
        session.add(row)
        session.flush()
    return row


def _build(session):
    session.execute(delete(Policy).where(Policy.slug == SLUG))
    session.expire_all()
    a, b, c = (_aspect(session, f"rd-aspect-{x}") for x in "abc")
    policy = Policy(
        slug=SLUG,
        name="Round trip",
        year=2020,
        summary="Original summary.",
        summary_source_url="https://example.org/summary",
    )
    session.add(policy)
    session.flush()
    run = EvidenceRun(
        policy_id=policy.id,
        query_version="v1",
        query_text="q",
        source_api="gdelt",
        result_count=2,
    )
    session.add(run)
    session.flush()
    first = SourceItem(
        run_id=run.id,
        policy_id=policy.id,
        url="https://example.org/1",
        outlet="Outlet One",
        published_at=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
        excerpt="First excerpt.",
        content_hash="a" * 64,
    )
    second = SourceItem(
        run_id=run.id,
        policy_id=policy.id,
        url="https://example.org/2",
        outlet="Outlet Two",
        excerpt="Second excerpt.",
        content_hash="b" * 64,
    )
    session.add_all([first, second])
    session.flush()
    approved = Indicator(
        policy_id=policy.id,
        aspect_id=a.id,
        name="Approved indicator",
        score=Decimal("72.50"),
        weight=Decimal("1.50"),
        description="Why.",
        status="approved",
        model="test-model",
        prompt_version="score_v3",
    )
    draft = Indicator(
        policy_id=policy.id,
        aspect_id=b.id,
        name="Draft indicator",
        score=Decimal(10),
        status="ai_draft",
    )
    session.add_all([approved, draft])
    session.flush()
    session.add(
        Evidence(
            indicator_id=approved.id,
            source_url="https://example.org/1",
            source_title="First article",
            source_tier=2,
            verification_multiplier=Decimal("0.80"),
            content_hash="e" * 64,
            quote="A quote.",
            source_item_id=first.id,
        )
    )
    session.add_all(
        [
            PolicyAim(
                policy_id=policy.id,
                text="Approved aim",
                source_url="https://example.org/aim",
                position=1,
                status="approved",
            ),
            PolicyAim(
                policy_id=policy.id,
                text="Draft aim",
                source_url="https://example.org/aim2",
                status="ai_draft",
            ),
            AspectReview(
                policy_id=policy.id,
                aspect_id=c.id,
                outcome="no_negative_evidence",
                reason="Checked three outlets.",
            ),
        ]
    )
    session.flush()
    return policy


def _wipe_children(session, policy):
    for model in (Indicator, PolicyAim, AspectReview, EvidenceRun):
        session.execute(delete(model).where(model.policy_id == policy.id))
    session.expire_all()


def test_export_leaves_out_unreviewed_rows(session):
    _build(session)
    entry = export_reviewed(session, [SLUG])["policies"][0]
    assert [i["name"] for i in entry["indicators"]] == ["Approved indicator"]
    assert [a["text"] for a in entry["aims"]] == ["Approved aim"]
    assert [r["aspect"] for r in entry["aspect_reviews"]] == ["rd-aspect-c"]
    assert len(entry["source_items"]) == 2
    evidence = entry["indicators"][0]["evidence"]
    assert evidence[0]["source_item"] == "a" * 64


def test_round_trip_restores_everything(session):
    policy = _build(session)
    before = export_reviewed(session, [SLUG])
    _wipe_children(session, policy)
    policy = session.scalar(select(Policy).where(Policy.slug == SLUG))
    policy.summary = "Changed on the live copy."
    session.flush()

    created = import_reviewed(session, before)

    assert created == {
        "source_items": 2,
        "indicators": 1,
        "evidence": 1,
        "aims": 1,
        "reviews": 1,
        "withdrawn": 0,
    }
    assert export_reviewed(session, [SLUG]) == before


def test_second_import_creates_nothing(session):
    policy = _build(session)
    before = export_reviewed(session, [SLUG])
    _wipe_children(session, policy)
    import_reviewed(session, before)

    again = import_reviewed(session, before)

    assert set(again.values()) == {0}
    assert export_reviewed(session, [SLUG]) == before


def test_unknown_policy_fails_loudly(session):
    with pytest.raises(ValueError, match="unknown policy"):
        import_reviewed(session, {"format": 1, "policies": [{"slug": "nope"}]})


def test_unknown_aspect_fails_loudly(session):
    _build(session)
    data = copy.deepcopy(export_reviewed(session, [SLUG]))
    data["policies"][0]["indicators"][0]["aspect"] = "no-such-aspect"
    with pytest.raises(ValueError, match="unknown aspect"):
        import_reviewed(session, data)


def test_unsupported_format_is_refused(session):
    with pytest.raises(ValueError, match="unsupported"):
        import_reviewed(session, {"format": 99, "policies": []})


def test_export_cuts_long_excerpts_and_import_keeps_full_text(session):
    policy = _build(session)
    item = session.scalar(
        select(SourceItem).where(SourceItem.content_hash == "a" * 64)
    )
    item.excerpt = "x" * 2000
    session.flush()

    data = export_reviewed(session, [SLUG])
    exported = next(
        s for s in data["policies"][0]["source_items"] if s["content_hash"] == "a" * 64
    )
    assert len(exported["excerpt"]) == 500

    import_reviewed(session, data)
    session.refresh(item)
    assert len(item.excerpt) == 2000
    assert policy.slug == SLUG