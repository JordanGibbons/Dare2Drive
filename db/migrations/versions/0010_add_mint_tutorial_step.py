"""Add 'mint' value to tutorialstep enum

Revision ID: 0010_add_mint_tutorial_step
Revises: 0009_create_rig_titles
Create Date: 2026-04-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010_add_mint_tutorial_step"
down_revision: Union[str, None] = "0009_create_rig_titles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL requires enum value additions to be outside a transaction
    # when using ADD VALUE; Alembic handles this automatically.
    op.execute("ALTER TYPE tutorialstep ADD VALUE IF NOT EXISTS 'mint' BEFORE 'garage'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from an existing enum type.
    pass
