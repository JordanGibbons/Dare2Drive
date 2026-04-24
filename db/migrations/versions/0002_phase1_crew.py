"""phase 1 crew sector

Revision ID: 0002_phase1_crew
Revises: 0001_initial
Create Date: 2026-04-24

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002_phase1_crew"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


CREW_ARCHETYPE_VALUES = ("pilot", "engineer", "gunner", "navigator", "medic")
RARITY_VALUES = ("common", "uncommon", "rare", "epic", "legendary", "ghost")


def upgrade() -> None:
    crew_archetype = postgresql.ENUM(
        *CREW_ARCHETYPE_VALUES, name="crewarchetype", create_type=False
    )
    crew_archetype.create(op.get_bind(), checkfirst=True)

    rarity = postgresql.ENUM(*RARITY_VALUES, name="rarity", create_type=False)

    op.create_table(
        "crew_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("first_name", sa.String(60), nullable=False),
        sa.Column("last_name", sa.String(60), nullable=False),
        sa.Column("callsign", sa.String(60), nullable=False),
        sa.Column("archetype", crew_archetype, nullable=False),
        sa.Column("rarity", rarity, nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("portrait_key", sa.String(60), nullable=True),
        sa.Column(
            "acquired_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "first_name",
            "last_name",
            "callsign",
            name="uq_crew_members_user_name",
        ),
    )
    op.create_index("ix_crew_members_user_archetype", "crew_members", ["user_id", "archetype"])

    op.create_table(
        "crew_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "crew_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crew_members.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "build_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("builds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("archetype", crew_archetype, nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("build_id", "archetype", name="uq_crew_assignments_build_archetype"),
    )

    op.create_table(
        "crew_daily_leads",
        sa.Column(
            "user_id",
            sa.String(20),
            sa.ForeignKey("users.discord_id"),
            primary_key=True,
        ),
        sa.Column("rolled_for_date", sa.Date(), primary_key=True),
        sa.Column("archetype", crew_archetype, nullable=False),
        sa.Column("rarity", rarity, nullable=False),
        sa.Column("first_name", sa.String(60), nullable=False),
        sa.Column("last_name", sa.String(60), nullable=False),
        sa.Column("callsign", sa.String(60), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("crew_daily_leads")
    op.drop_table("crew_assignments")
    op.drop_index("ix_crew_members_user_archetype", table_name="crew_members")
    op.drop_table("crew_members")
    sa.Enum(name="crewarchetype").drop(op.get_bind(), checkfirst=True)
