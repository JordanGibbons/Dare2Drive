"""Phase 2b — expeditions

Revision ID: 0004_phase2b_expeditions
Revises: 0003_phase2a_scheduler
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_phase2b_expeditions"
down_revision = "0003_phase2a_scheduler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. New enums (names match ORM models: build_activity, expedition_state)
    expedition_state = postgresql.ENUM(
        "active",
        "completed",
        "failed",
        name="expedition_state",
    )
    expedition_state.create(bind, checkfirst=True)

    build_activity = postgresql.ENUM(
        "idle",
        "on_expedition",
        name="build_activity",
    )
    build_activity.create(bind, checkfirst=True)

    # 2. Extend existing enums (Postgres ALTER TYPE ADD VALUE — non-transactional).
    # NOTE: Existing enums from prior migrations use concatenated lowercase names
    # (crewactivity, jobtype, rewardsourcetype) — no underscores.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE crewactivity ADD VALUE IF NOT EXISTS 'on_expedition'")
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'expedition_event'")
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'expedition_auto_resolve'")
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'expedition_resolve'")
        op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'expedition_complete'")
        op.execute("ALTER TYPE rewardsourcetype ADD VALUE IF NOT EXISTS 'expedition_outcome'")

    # 3. Add columns to existing tables
    op.add_column(
        "builds",
        sa.Column(
            "current_activity",
            postgresql.ENUM(name="build_activity", create_type=False),
            nullable=False,
            server_default="idle",
        ),
    )
    op.add_column(
        "builds",
        sa.Column("current_activity_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "crew_members",
        sa.Column("injured_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "crew_members",
        sa.Column(
            "stats",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
    )

    # 4. expeditions table
    op.create_table(
        "expeditions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "build_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("builds.id"),
            nullable=False,
        ),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column(
            "state",
            postgresql.ENUM(name="expedition_state", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scene_log", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("outcome_summary", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_expeditions_user_state", "expeditions", ["user_id", "state"])
    op.create_index(
        "ix_expeditions_active_per_build",
        "expeditions",
        ["build_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )

    # 5. expedition_crew_assignments table.
    # crew_archetype enum (name="crew_archetype", with underscore) was introduced
    # alongside the ORM models in this branch and exists in the DB.
    op.create_table(
        "expedition_crew_assignments",
        sa.Column(
            "expedition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expeditions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "crew_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crew_members.id"),
            primary_key=True,
        ),
        sa.Column(
            "archetype",
            postgresql.ENUM(name="crew_archetype", create_type=False),
            nullable=False,
        ),
        sa.UniqueConstraint("expedition_id", "archetype", name="uq_expedition_archetype_slot"),
    )


def downgrade() -> None:
    op.drop_table("expedition_crew_assignments")
    op.drop_index("ix_expeditions_active_per_build", table_name="expeditions")
    op.drop_index("ix_expeditions_user_state", table_name="expeditions")
    op.drop_table("expeditions")

    op.drop_column("crew_members", "stats")
    op.drop_column("crew_members", "injured_until")
    op.drop_column("builds", "current_activity_id")
    op.drop_column("builds", "current_activity")

    # Note: Postgres does NOT support DROP VALUE on ENUM. The added enum
    # values for crewactivity, jobtype, rewardsourcetype are NOT removed
    # on downgrade. This is a known Postgres limitation. The new enums
    # (expedition_state, build_activity) are dropped below since nothing
    # references them after the column drops above.
    op.execute("DROP TYPE IF EXISTS expedition_state")
    op.execute("DROP TYPE IF EXISTS build_activity")
