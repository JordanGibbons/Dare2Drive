"""Add last_daily timestamp to users table

Revision ID: 0005_add_last_daily
Revises: 0004_market_listing_user_card_id
Create Date: 2026-04-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_add_last_daily"
down_revision: Union[str, None] = "0004_market_listing_user_card_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_daily", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_daily")
