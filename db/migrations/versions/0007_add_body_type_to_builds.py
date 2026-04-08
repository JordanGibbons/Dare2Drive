"""Add body_type and core_locked to builds table

Revision ID: 0007_add_body_type_to_builds
Revises: 0006_add_races_used
Create Date: 2026-04-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_add_body_type_to_builds"
down_revision: Union[str, None] = "0006_add_races_used"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

body_type_enum = sa.Enum("muscle", "sport", "compact", name="bodytype")


def upgrade() -> None:
    # Add body_type as nullable first so we can backfill
    op.add_column(
        "builds",
        sa.Column("body_type", body_type_enum, nullable=True),
    )

    # Backfill from the owning user's body_type
    op.execute("""
        UPDATE builds
        SET body_type = users.body_type
        FROM users
        WHERE builds.user_id = users.discord_id
        """)

    # Now make it non-nullable
    op.alter_column("builds", "body_type", nullable=False)

    op.add_column(
        "builds",
        sa.Column("core_locked", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("builds", "core_locked")
    op.drop_column("builds", "body_type")
