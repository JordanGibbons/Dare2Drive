"""Add compatible_body_types to cards table

Revision ID: 0008_add_compatible_body_types_to_cards
Revises: 0007_add_body_type_to_builds
Create Date: 2026-04-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008_add_compatible_body_types_to_cards"
down_revision: Union[str, None] = "0007_add_body_type_to_builds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cards",
        sa.Column("compatible_body_types", JSONB(), nullable=True),
    )
    # Existing cards default to null (universal — compatible with all body types)


def downgrade() -> None:
    op.drop_column("cards", "compatible_body_types")
