"""Phase 2a — schema-level tests for new enums and models."""

from __future__ import annotations


def test_job_type_enum_values():
    from db.models import JobType

    assert {j.value for j in JobType} == {"timer_complete", "accrual_tick"}


def test_job_state_enum_values():
    from db.models import JobState

    assert {s.value for s in JobState} == {
        "pending",
        "claimed",
        "completed",
        "failed",
        "cancelled",
    }


def test_timer_type_enum_values():
    from db.models import TimerType

    assert {t.value for t in TimerType} == {"training", "research", "ship_build"}


def test_timer_state_enum_values():
    from db.models import TimerState

    assert {s.value for s in TimerState} == {"active", "completed", "cancelled"}


def test_station_type_enum_values():
    from db.models import StationType

    assert {s.value for s in StationType} == {"cargo_run", "repair_bay", "watch_tower"}


def test_reward_source_type_enum_values():
    from db.models import RewardSourceType

    assert {s.value for s in RewardSourceType} == {
        "timer_complete",
        "accrual_tick",
        "accrual_claim",
        "timer_cancel_refund",
    }


def test_crew_activity_enum_values():
    from db.models import CrewActivity

    assert {a.value for a in CrewActivity} == {
        "idle",
        "on_build",
        "training",
        "researching",
        "on_station",
    }
