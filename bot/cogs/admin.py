"""Admin cog — dev/admin-only commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, update

from config.logging import get_logger
from db.models import Build, MarketListing, RigTitle, TutorialStep, User, UserCard, WreckLog
from db.session import async_session

log = get_logger(__name__)


async def _delete_player_data(session, user_id: str, user: User) -> None:
    """
    Delete all rows owned by *user_id* in the correct FK order, then the user row.

    builds ↔ rig_titles form a circular FK:
      builds.rig_title_id → rig_titles.id
      rig_titles.build_id → builds.id

    Breaking the cycle: NULL out builds.rig_title_id first so rig_titles can
    be deleted, then delete builds, then the user.

    Full order:
      wreck_logs → market_listings → user_cards
      → NULL builds.rig_title_id → rig_titles → builds → user
    """
    await session.execute(delete(WreckLog).where(WreckLog.user_id == user_id))
    await session.execute(delete(MarketListing).where(MarketListing.seller_id == user_id))
    await session.execute(delete(UserCard).where(UserCard.user_id == user_id))
    # Break the circular FK before deleting either side
    await session.execute(update(Build).where(Build.user_id == user_id).values(rig_title_id=None))
    await session.execute(delete(RigTitle).where(RigTitle.owner_id == user_id))
    await session.execute(delete(Build).where(Build.user_id == user_id))
    await session.delete(user)


def is_admin():
    """Check that the user has administrator permission in the server."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await interaction.response.send_message(
                "Admin commands only work in a server.", ephemeral=True
            )
            return False
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "You don't have permission to use admin commands.", ephemeral=True
            )
            return False
        return True

    return app_commands.check(predicate)


class AdminCog(commands.Cog):
    """Admin-only commands for testing and management."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="admin_reset_player",
        description="[ADMIN] Fully wipe a player's account so they can /start again",
    )
    @app_commands.describe(target="The player to reset")
    @is_admin()
    async def reset_player(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)

        user_id = str(target.id)

        async with async_session() as session:
            user = await session.get(User, user_id)
            if not user:
                await interaction.followup.send(
                    f"{target.display_name} doesn't have an account.", ephemeral=True
                )
                return

            await _delete_player_data(session, user_id, user)
            await session.commit()

        log.info(
            "Admin %s wiped account for %s (%s)", interaction.user.id, target.display_name, user_id
        )
        await interaction.followup.send(
            f"✅ Wiped **{target.display_name}**'s account. They can use `/start` again.",
            ephemeral=True,
        )

    @app_commands.command(
        name="admin_set_tutorial_step",
        description="[ADMIN] Set a player's tutorial step directly",
    )
    @app_commands.describe(
        target="The player to update",
        step="Tutorial step to set",
    )
    @app_commands.choices(
        step=[app_commands.Choice(name=s.value, value=s.value) for s in TutorialStep]
    )
    @is_admin()
    async def set_tutorial_step(
        self, interaction: discord.Interaction, target: discord.Member, step: str
    ) -> None:

        async with async_session() as session:
            user = await session.get(User, str(target.id))
            if not user:
                await interaction.response.send_message(
                    f"{target.display_name} doesn't have an account.", ephemeral=True
                )
                return

            old_step = user.tutorial_step.value
            user.tutorial_step = TutorialStep(step)
            await session.commit()

        await interaction.response.send_message(
            f"✅ Set **{target.display_name}**'s tutorial step: `{old_step}` → `{step}`",
            ephemeral=True,
        )

    @app_commands.command(
        name="admin_give_creds",
        description="[ADMIN] Add or remove Creds from a player's balance",
    )
    @app_commands.describe(
        target="The player to modify",
        amount="Amount of Creds (positive to add, negative to remove)",
    )
    @is_admin()
    async def give_creds(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        amount: int,
    ) -> None:
        async with async_session() as session:
            user = await session.get(User, str(target.id))
            if not user:
                await interaction.response.send_message(
                    f"{target.display_name} doesn't have an account.", ephemeral=True
                )
                return

            old_balance = user.currency
            user.currency = max(0, user.currency + amount)
            new_balance = user.currency
            await session.commit()

        action = "Added" if amount >= 0 else "Removed"
        log.info(
            "Admin %s %s %d creds for %s (%s → %s)",
            interaction.user.id,
            action.lower(),
            abs(amount),
            target.display_name,
            old_balance,
            new_balance,
        )
        await interaction.response.send_message(
            f"✅ {action} **{abs(amount)} Creds** for **{target.display_name}** "
            f"({old_balance} → {new_balance})",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
