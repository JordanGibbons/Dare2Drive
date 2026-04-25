"""Smoke test: HiringCog loads and registers its commands."""

from __future__ import annotations


def test_hiring_cog_imports():
    from bot.cogs import hiring  # noqa: F401

    assert hasattr(hiring, "HiringCog")


def test_hiring_cog_registers_commands():
    import discord
    from discord.ext import commands

    from bot.cogs.hiring import HiringCog

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    cog = HiringCog(bot)
    command_names = {c.name for c in cog.walk_app_commands()}
    assert {"dossier", "hire", "crew", "assign", "unassign"} <= command_names
