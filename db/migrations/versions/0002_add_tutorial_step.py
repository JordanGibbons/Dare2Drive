"""Add tutorial_step column to users table

Revision ID: 0002_add_tutorial_step
Revises: 0001_initial
Create Date: 2026-04-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_add_tutorial_step"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

tutorialstep_enum = postgresql.ENUM(
    "started",
    "inventory",
    "inspect",
    "equip",
    "garage",
    "race",
    "pack",
    "complete",
    name="tutorialstep",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "started",
        "inventory",
        "inspect",
        "equip",
        "garage",
        "race",
        "pack",
        "complete",
        name="tutorialstep",
    ).create(bind, checkfirst=True)

    op.add_column(
        "users",
        sa.Column(
            "tutorial_step",
            tutorialstep_enum,
            nullable=False,
            server_default="complete",  # Existing players are "done"
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "tutorial_step")
    bind = op.get_bind()
    postgresql.ENUM(name="tutorialstep").drop(bind, checkfirst=True)
