"""phase 2a scheduler foundation

Revision ID: 0003_phase2a_scheduler
Revises: 0002_phase1_crew
Create Date: 2026-04-25

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_phase2a_scheduler"
down_revision = "0002_phase1_crew"
branch_labels = None
depends_on = None


JOB_TYPE = ("timer_complete", "accrual_tick")
JOB_STATE = ("pending", "claimed", "completed", "failed", "cancelled")
TIMER_TYPE = ("training", "research", "ship_build")
TIMER_STATE = ("active", "completed", "cancelled")
STATION_TYPE = ("cargo_run", "repair_bay", "watch_tower")
REWARD_SOURCE_TYPE = (
    "timer_complete",
    "accrual_tick",
    "accrual_claim",
    "timer_cancel_refund",
)
CREW_ACTIVITY = ("idle", "on_build", "training", "researching", "on_station")

DEFAULT_NOTIFICATION_PREFS = '{"timer_completion": "dm", "accrual_threshold": "dm", "_version": 1}'


def upgrade() -> None:
    bind = op.get_bind()

    # Create new enums.
    job_type = postgresql.ENUM(*JOB_TYPE, name="jobtype", create_type=False)
    job_state = postgresql.ENUM(*JOB_STATE, name="jobstate", create_type=False)
    timer_type = postgresql.ENUM(*TIMER_TYPE, name="timertype", create_type=False)
    timer_state = postgresql.ENUM(*TIMER_STATE, name="timerstate", create_type=False)
    station_type = postgresql.ENUM(*STATION_TYPE, name="stationtype", create_type=False)
    reward_source = postgresql.ENUM(*REWARD_SOURCE_TYPE, name="rewardsourcetype", create_type=False)
    crew_activity = postgresql.ENUM(*CREW_ACTIVITY, name="crewactivity", create_type=False)
    for e in (
        job_type,
        job_state,
        timer_type,
        timer_state,
        station_type,
        reward_source,
        crew_activity,
    ):
        e.create(bind, checkfirst=True)

    # scheduled_jobs
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", job_state, nullable=False, server_default="pending"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_scheduled_jobs_pending_due",
        "scheduled_jobs",
        ["state", "scheduled_for"],
        postgresql_where=sa.text("state IN ('pending', 'claimed')"),
    )

    # timers
    op.create_table(
        "timers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("timer_type", timer_type, nullable=False),
        sa.Column("recipe_id", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", timer_state, nullable=False, server_default="active"),
        sa.Column(
            "linked_scheduled_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_jobs.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ux_timers_one_research_active",
        "timers",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("timer_type = 'research' AND state = 'active'"),
    )
    op.create_index(
        "ux_timers_one_ship_build_active",
        "timers",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("timer_type = 'ship_build' AND state = 'active'"),
    )

    # station_assignments
    op.create_table(
        "station_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("station_type", station_type, nullable=False),
        sa.Column(
            "crew_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crew_members.id"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_yield_tick_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("pending_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ux_station_assignments_user_type_active",
        "station_assignments",
        ["user_id", "station_type"],
        unique=True,
        postgresql_where=sa.text("recalled_at IS NULL"),
    )

    # reward_ledger
    op.create_table(
        "reward_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_type", reward_source, nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("delta", postgresql.JSONB, nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("source_type", "source_id", name="ux_reward_ledger_source"),
    )

    # Extend crew_members
    op.add_column(
        "crew_members",
        sa.Column("current_activity", crew_activity, nullable=False, server_default="idle"),
    )
    op.add_column(
        "crew_members",
        sa.Column("current_activity_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Extend users
    op.add_column(
        "users",
        sa.Column(
            "notification_prefs",
            postgresql.JSONB,
            nullable=False,
            server_default=DEFAULT_NOTIFICATION_PREFS,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notification_prefs")
    op.drop_column("crew_members", "current_activity_id")
    op.drop_column("crew_members", "current_activity")
    op.drop_table("reward_ledger")
    op.drop_index("ux_station_assignments_user_type_active", table_name="station_assignments")
    op.drop_table("station_assignments")
    op.drop_index("ux_timers_one_ship_build_active", table_name="timers")
    op.drop_index("ux_timers_one_research_active", table_name="timers")
    op.drop_table("timers")
    op.drop_index("ix_scheduled_jobs_pending_due", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")

    bind = op.get_bind()
    for name in (
        "crewactivity",
        "rewardsourcetype",
        "stationtype",
        "timerstate",
        "timertype",
        "jobstate",
        "jobtype",
    ):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
