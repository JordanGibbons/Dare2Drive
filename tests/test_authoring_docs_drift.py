"""CI gate: docs/authoring/expeditions.md must match the auto-generated tables."""

from __future__ import annotations

import subprocess
import sys


def test_authoring_docs_in_sync_with_engine():
    """Fail if the committed guide doesn't match what build_authoring_docs.py produces."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.build_authoring_docs", "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "docs/authoring/expeditions.md is out of date relative to the engine "
        "registries (engine/stat_namespace.py, engine/effect_registry.py).\n"
        "Run `python -m scripts.build_authoring_docs` and commit the result.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
