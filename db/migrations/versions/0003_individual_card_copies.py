"""Individual card copies — serial numbers and stat variance

Drop quantity from user_cards, add serial_number + stat_modifiers.
Expand existing quantity>1 rows into individual rows.
Add total_minted to cards table.
Update build slots from card_id → user_card_id.

Revision ID: 0003_individual_card_copies
Revises: 0002_add_tutorial_step
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0003_individual_card_copies"
down_revision: Union[str, None] = "0002_add_tutorial_step"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add total_minted to cards
    op.add_column("cards", sa.Column("total_minted", sa.Integer, nullable=False, server_default="0"))

    # 2. Add new columns to user_cards
    op.add_column("user_cards", sa.Column("serial_number", sa.Integer, nullable=False, server_default="0"))
    op.add_column("user_cards", sa.Column("stat_modifiers", postgresql.JSONB, nullable=False, server_default="{}"))

    # 3. Expand quantity>1 rows into individual rows
    #    For each user_card with quantity>1, keep the original row (qty=1) and insert (qty-1) copies
    rows = conn.execute(
        sa.text("SELECT id, user_id, card_id, quantity, is_foil FROM user_cards WHERE quantity > 1")
    ).fetchall()

    for row in rows:
        uc_id, user_id, card_id, qty, is_foil = row
        # Insert (qty-1) new rows for the extra copies
        for _ in range(qty - 1):
            conn.execute(
                sa.text(
                    "INSERT INTO user_cards (id, user_id, card_id, serial_number, stat_modifiers, is_foil, acquired_at) "
                    "VALUES (gen_random_uuid(), :user_id, :card_id, 0, '{}', :is_foil, now())"
                ),
                {"user_id": user_id, "card_id": card_id, "is_foil": is_foil},
            )

    # 4. Assign serial numbers: for each card, number all user_cards sequentially
    card_ids = conn.execute(sa.text("SELECT DISTINCT card_id FROM user_cards")).fetchall()
    for (card_id,) in card_ids:
        uc_rows = conn.execute(
            sa.text("SELECT id FROM user_cards WHERE card_id = :card_id ORDER BY acquired_at, id"),
            {"card_id": card_id},
        ).fetchall()
        for i, (uc_id,) in enumerate(uc_rows, start=1):
            conn.execute(
                sa.text("UPDATE user_cards SET serial_number = :sn WHERE id = :id"),
                {"sn": i, "id": uc_id},
            )
        # Update total_minted on the card
        conn.execute(
            sa.text("UPDATE cards SET total_minted = :count WHERE id = :card_id"),
            {"count": len(uc_rows), "card_id": card_id},
        )

    # 5. Update build slots: card_id → user_card_id
    #    For each build slot that has a card_id, find the user's first user_card for that card
    builds = conn.execute(sa.text("SELECT id, user_id, slots FROM builds")).fetchall()
    for build_id, user_id, slots in builds:
        if not slots:
            continue
        new_slots = dict(slots)
        changed = False
        for slot_name, card_id in slots.items():
            if card_id is None:
                continue
            # Find the user's first unequipped copy of this card
            uc = conn.execute(
                sa.text(
                    "SELECT id FROM user_cards "
                    "WHERE user_id = :user_id AND card_id = :card_id "
                    "ORDER BY serial_number LIMIT 1"
                ),
                {"user_id": user_id, "card_id": card_id},
            ).fetchone()
            if uc:
                new_slots[slot_name] = str(uc[0])
                changed = True
            else:
                new_slots[slot_name] = None
                changed = True
        if changed:
            import json
            conn.execute(
                sa.text("UPDATE builds SET slots = :slots::jsonb WHERE id = :id"),
                {"slots": json.dumps(new_slots), "id": build_id},
            )

    # 6. Drop quantity column
    op.drop_column("user_cards", "quantity")


def downgrade() -> None:
    # Add quantity back
    op.add_column("user_cards", sa.Column("quantity", sa.Integer, nullable=False, server_default="1"))

    # Rebuild build slots from user_card_id → card_id is not trivially reversible.
    # Leave slots as-is; a full revert would need manual intervention.

    op.drop_column("user_cards", "stat_modifiers")
    op.drop_column("user_cards", "serial_number")
    op.drop_column("cards", "total_minted")
