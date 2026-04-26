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


def test_expedition_columns():
    from db.models import Expedition

    cols = {c.name for c in Expedition.__table__.columns}
    assert cols >= {
        "id",
        "user_id",
        "build_id",
        "template_id",
        "state",
        "started_at",
        "completes_at",
        "correlation_id",
        "scene_log",
        "outcome_summary",
        "created_at",
    }


def test_expedition_crew_assignment_columns():
    from db.models import ExpeditionCrewAssignment

    cols = {c.name for c in ExpeditionCrewAssignment.__table__.columns}
    assert cols >= {"expedition_id", "crew_id", "archetype"}


def test_expedition_crew_assignment_unique_archetype_per_expedition():
    """Only one crew per archetype slot per expedition."""
    from db.models import ExpeditionCrewAssignment

    constraints = ExpeditionCrewAssignment.__table__.constraints
    unique_pairs = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("archetype", "expedition_id") in unique_pairs


def test_build_has_current_activity_columns():
    from db.models import Build

    cols = {c.name for c in Build.__table__.columns}
    assert {"current_activity", "current_activity_id"} <= cols


def test_crew_member_has_injured_until_column():
    from db.models import CrewMember

    cols = {c.name for c in CrewMember.__table__.columns}
    assert "injured_until" in cols


def test_expedition_active_per_build_partial_unique_index():
    """At most one ACTIVE expedition per build, enforced at DB level."""
    from db.models import Expedition

    # Find a partial unique index on build_id with the ACTIVE-state predicate.
    indexes = list(Expedition.__table__.indexes)
    matched = [
        ix
        for ix in indexes
        if ix.unique
        and {c.name for c in ix.columns} == {"build_id"}
        and "active"
        in (
            str(ix.dialect_options.get("postgresql", {}).get("where", "")).lower()
            + str(ix.kwargs.get("postgresql_where", "")).lower()
        )
    ]
    assert matched, "expected a partial unique index on Expedition(build_id) WHERE state = 'active'"
