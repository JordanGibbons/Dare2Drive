"""Phase 2b — schema-level tests for new enums and models."""

from __future__ import annotations


def test_expedition_state_enum_values():
    from db.models import ExpeditionState

    assert {s.value for s in ExpeditionState} == {"active", "completed", "failed"}


def test_build_activity_enum_values():
    from db.models import BuildActivity

    assert {a.value for a in BuildActivity} == {"idle", "on_expedition"}


def test_crew_activity_enum_extended_with_on_expedition():
    from db.models import CrewActivity

    assert "on_expedition" in {a.value for a in CrewActivity}


def test_job_type_enum_extended_with_expedition_jobs():
    from db.models import JobType

    values = {j.value for j in JobType}
    assert {
        "expedition_event",
        "expedition_auto_resolve",
        "expedition_resolve",
        "expedition_complete",
    } <= values


def test_reward_source_type_extended_with_expedition_outcome():
    from db.models import RewardSourceType

    assert "expedition_outcome" in {s.value for s in RewardSourceType}
