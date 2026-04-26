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


def test_scheduled_job_columns():
    from db.models import ScheduledJob

    cols = {c.name for c in ScheduledJob.__table__.columns}
    assert cols >= {
        "id",
        "user_id",
        "job_type",
        "payload",
        "scheduled_for",
        "state",
        "claimed_at",
        "completed_at",
        "attempts",
        "last_error",
        "created_at",
        "updated_at",
    }


def test_timer_columns():
    from db.models import Timer

    cols = {c.name for c in Timer.__table__.columns}
    assert cols >= {
        "id",
        "user_id",
        "timer_type",
        "recipe_id",
        "payload",
        "started_at",
        "completes_at",
        "state",
        "linked_scheduled_job_id",
        "created_at",
        "updated_at",
    }


def test_station_assignment_columns():
    from db.models import StationAssignment

    cols = {c.name for c in StationAssignment.__table__.columns}
    assert cols >= {
        "id",
        "user_id",
        "station_type",
        "crew_id",
        "assigned_at",
        "last_yield_tick_at",
        "pending_credits",
        "pending_xp",
        "recalled_at",
        "created_at",
        "updated_at",
    }


def test_reward_ledger_columns():
    from db.models import RewardLedger

    cols = {c.name for c in RewardLedger.__table__.columns}
    assert cols >= {"id", "user_id", "source_type", "source_id", "delta", "applied_at"}


def test_crew_member_has_current_activity_columns():
    from db.models import CrewMember

    cols = {c.name for c in CrewMember.__table__.columns}
    assert {"current_activity", "current_activity_id"} <= cols


def test_user_has_notification_prefs():
    from db.models import User

    cols = {c.name for c in User.__table__.columns}
    assert "notification_prefs" in cols
