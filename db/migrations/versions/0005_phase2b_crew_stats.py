"""Phase 2b — add per-crew stats JSONB column

Revision ID: 0005_phase2b_crew_stats
Revises: 0004_phase2b_expeditions
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_phase2b_crew_stats"
down_revision = "0004_phase2b_expeditions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crew_members",
        sa.Column(
            "stats",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("crew_members", "stats")
