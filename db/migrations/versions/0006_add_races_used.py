"""Add races_used counter to user_cards table

Revision ID: 0006_add_races_used
Revises: 0005_add_last_daily
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_add_races_used"
down_revision: Union[str, None] = "0005_add_last_daily"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_cards", sa.Column("races_used", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("user_cards", "races_used")
