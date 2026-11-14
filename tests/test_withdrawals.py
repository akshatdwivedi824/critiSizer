from decimal import Decimal

import pytest
from factories import fill_policy, make_aspects
from sqlalchemy import select

from critisizer.audit import record_audit
from critisizer.models import AuditLog, Indicator
from critisizer.reviewed_data import (
    WITHDRAW_ACTION,
    export_reviewed,
    import_reviewed,
)


@pytest.fixture
def aspects(session):
    return make_aspects(session)


def _setup(session, aspects):
    policy = fill_policy(session, aspects, "p", {"outcome_failure": (60, [1.0])})
    indicator = session.scalars(
        select(Indicator).where(Indicator.policy_id == policy.id)
    ).one()
    return policy, indicator


def _log_withdrawal(session, indicator, reason="claim, not evidence"):
    record_audit(
        session,
        WITHDRAW_ACTION,
        "indicator",
        indicator.id,
        {
            "policy": "p",
            "aspect": "outcome_failure",
            "name": indicator.name,
            "reason": reason,
        },
    )


def test_a_withdrawn_indicator_is_listed_and_not_exported_as_approved(
    session, aspects
):
    _, indicator = _setup(session, aspects)
    indicator.status = "rejected"
    _log_withdrawal(session, indicator)
    session.commit()

    entry = export_reviewed(session, ["p"])["policies"][0]
    assert entry["indicators"] == []
    assert entry["withdrawn"] == [
        {
            "aspect": "outcome_failure",
            "name": indicator.name,
            "reason": "claim, not evidence",
        }
    ]


def test_a_key_approved_again_is_not_listed_as_withdrawn(session, aspects):
    _, indicator = _setup(session, aspects)
    _log_withdrawal(session, indicator)
    session.commit()  # the indicator is still approved

    entry = export_reviewed(session, ["p"])["policies"][0]
    assert entry["withdrawn"] == []
    assert len(entry["indicators"]) == 1


def test_a_rejected_twin_of_an_approved_indicator_does_not_withdraw_it(
    session, aspects
):
    policy, approved = _setup(session, aspects)
    twin = Indicator(
        policy_id=policy.id,
        aspect_id=approved.aspect_id,
        name=approved.name,
        score=Decimal(60),
        status="rejected",
    )
    session.add(twin)
    session.flush()
    _log_withdrawal(session, twin)
    session.commit()

    entry = export_reviewed(session, ["p"])["policies"][0]
    assert entry["withdrawn"] == []
    assert len(entry["indicators"]) == 1


def test_import_rejects_the_matching_approved_indicator_once(session, aspects):
    _, indicator = _setup(session, aspects)
    session.commit()
    data = export_reviewed(session, ["p"])
    entry = data["policies"][0]
    entry["indicators"] = []
    entry["withdrawn"] = [
        {"aspect": "outcome_failure", "name": indicator.name, "reason": "claim"}
    ]

    assert import_reviewed(session, data)["withdrawn"] == 1
    session.commit()
    session.refresh(indicator)
    assert indicator.status == "rejected"
    logged = session.scalars(
        select(AuditLog).where(AuditLog.action == WITHDRAW_ACTION)
    ).all()
    assert [row.details["via"] for row in logged] == ["import"]

    # A second import finds nothing approved left to withdraw.
    assert import_reviewed(session, data)["withdrawn"] == 0


def test_files_without_a_withdrawn_list_still_import(session, aspects):
    _setup(session, aspects)
    session.commit()
    data = export_reviewed(session, ["p"])
    del data["policies"][0]["withdrawn"]
    assert import_reviewed(session, data)["withdrawn"] == 0