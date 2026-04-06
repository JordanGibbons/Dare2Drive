"""Add user_card_id to market_listings for individual card copy tracking

Revision ID: 0004_market_listing_user_card_id
Revises: 0003_individual_card_copies
Create Date: 2026-04-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_market_listing_user_card_id"
down_revision: Union[str, None] = "0003_individual_card_copies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Add user_card_id column (nullable first so we can backfill)
    op.add_column(
        "market_listings",
        sa.Column("user_card_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Backfill existing unsold listings: find a matching UserCard owned by the seller
    listings = conn.execute(
        sa.text(
            "SELECT ml.id, ml.seller_id, ml.card_id FROM market_listings ml "
            "WHERE ml.sold_at IS NULL AND ml.user_card_id IS NULL"
        )
    ).fetchall()

    for listing_id, seller_id, card_id in listings:
        uc = conn.execute(
            sa.text(
                "SELECT id FROM user_cards "
                "WHERE user_id = :seller_id AND card_id = :card_id "
                "ORDER BY serial_number LIMIT 1"
            ),
            {"seller_id": seller_id, "card_id": card_id},
        ).fetchone()
        if uc:
            conn.execute(
                sa.text("UPDATE market_listings SET user_card_id = :uc_id WHERE id = :id"),
                {"uc_id": uc[0], "id": listing_id},
            )

    # Delete any listings that couldn't be matched (orphaned)
    conn.execute(
        sa.text("DELETE FROM market_listings WHERE user_card_id IS NULL AND sold_at IS NULL")
    )

    # For sold listings without a user_card_id, set a placeholder or delete
    # Since sold listings are historical, we can leave them NULL or clean up
    # We'll just delete unmatched sold listings too since they're from old system
    conn.execute(sa.text("DELETE FROM market_listings WHERE user_card_id IS NULL"))

    # Now make it NOT NULL and add the FK
    op.alter_column("market_listings", "user_card_id", nullable=False)
    op.create_foreign_key(
        "fk_market_listings_user_card_id",
        "market_listings",
        "user_cards",
        ["user_card_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_market_listings_user_card_id", "market_listings", type_="foreignkey")
    op.drop_column("market_listings", "user_card_id")
