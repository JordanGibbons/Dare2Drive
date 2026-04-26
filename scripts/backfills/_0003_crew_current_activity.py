from importlib import import_module  # noqa: F401, F403

_real = import_module("scripts.backfills.0003_crew_current_activity")
BACKFILL_SQL = _real.BACKFILL_SQL
