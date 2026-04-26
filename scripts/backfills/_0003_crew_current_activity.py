from importlib import import_module

_real = import_module("scripts.backfills.0003_crew_current_activity")
BACKFILL_SQL = _real.BACKFILL_SQL
