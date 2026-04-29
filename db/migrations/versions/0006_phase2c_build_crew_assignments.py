"""Phase 2c — build_crew_assignments

Revision ID: 0006_phase2c_build_crew
Revises: 0005_phase2b_crew_stats
Create Date: 2026-04-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_phase2c_build_crew"
down_revision = "0005_phase2b_crew_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "build_crew_assignments",
        sa.Column(
            "build_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("builds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "crew_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crew_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "archetype",
            postgresql.ENUM(name="crewarchetype", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("build_id", "archetype"),
        sa.UniqueConstraint("crew_id", name="uq_build_crew_assignments_crew_id"),
    )
    op.create_index(
        "ix_build_crew_assignments_crew_id",
        "build_crew_assignments",
        ["crew_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_build_crew_assignments_crew_id", table_name="build_crew_assignments")
    op.drop_table("build_crew_assignments")
