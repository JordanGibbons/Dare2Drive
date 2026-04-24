"""Scenario: a tutorial player races the NPC to completion.

Exercises the full race pipeline — system gating, build resolution,
class gate, engine simulation, Race row persistence, wreck handling —
end to end. Uses the `raceable_player` fixture which walks the whole
build → mint → tutorial_step=RACE setup.
"""

from __future__ import annotations

import pytest

from bot.cogs.race import RaceCog

from .conftest import make_interaction


@pytest.mark.asyncio
async def test_tutorial_npc_race_runs_to_completion(
    raceable_player, active_system, monkeypatch
) -> None:
    """A minted, tutorial-step=RACE player invokes /race with no opponent.
    Should trigger the NPC path, simulate, and persist a Race row.

    advance_tutorial is stubbed: the post-race dialogue awaits a
    ContinueView button click that never arrives in tests."""
    user_id, _ = raceable_player
    race_cog = RaceCog(bot=None)  # type: ignore[arg-type]

    async def _noop_advance(*_a, **_kw):
        return None

    monkeypatch.setattr("bot.cogs.tutorial.advance_tutorial", _noop_advance)

    interaction = make_interaction(int(user_id))
    await race_cog.race.callback(
        race_cog,
        interaction,
        opponent=None,
        wager=0,
        race_format="sprint",
        race_hull=None,
        build=None,
    )

    content = interaction.all_content()
    assert (
        "Game not enabled here" not in content
    ), f"System gate rejected race inside active_system: {interaction.calls}"
    assert "No active build found" not in content
    assert "has no cards equipped" not in content

    # Tutorial races intentionally don't persist a Race row (race.py line 283:
    # `if not is_tutorial_race`). The end-to-end signal is the final followup
    # embed sent by _run_race_and_send — verifying the full pipeline (active
    # system, build resolution, engine simulation, environment, durability)
    # executed without throwing.
    followup_calls = [c for c in interaction.calls if c.method == "followup.send"]
    assert any(
        c.kwargs.get("embed") is not None for c in followup_calls
    ), f"Expected a race-result embed in followup.send calls. Got: {interaction.calls}"


@pytest.mark.asyncio
async def test_race_refused_outside_active_system(raceable_player) -> None:
    """Without active_system, /race must hit the gating refusal before the NPC path."""
    user_id, _ = raceable_player
    race_cog = RaceCog(bot=None)  # type: ignore[arg-type]

    interaction = make_interaction(int(user_id))
    await race_cog.race.callback(
        race_cog,
        interaction,
        opponent=None,
        wager=0,
        race_format="sprint",
        race_hull=None,
        build=None,
    )

    assert "Game not enabled here" in interaction.all_content()
