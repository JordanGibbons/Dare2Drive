"""CLI entry point tests for the template validator."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def _write_valid(tmp_path: Path) -> Path:
    body = textwrap.dedent("""\
        id: cli_valid
        kind: scripted
        duration_minutes: 360
        response_window_minutes: 30
        cost_credits: 0
        crew_required: { min: 1, archetypes_any: [PILOT] }
        scenes:
          - id: opening
            narration: "Hi."
          - id: closing
            is_closing: true
            closings:
              - when: { default: true }
                body: "Bye."
                effects: []
        """)
    p = tmp_path / "cli_valid.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_cli_validate_returns_zero_for_valid(tmp_path):
    p = _write_valid(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "engine.expedition_template", "validate", str(p)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_cli_validate_returns_nonzero_for_invalid(tmp_path):
    body = textwrap.dedent("""\
        id: bad
        kind: nonsense
        duration_minutes: 360
        response_window_minutes: 30
        cost_credits: 0
        crew_required: { min: 1 }
        """)
    p = tmp_path / "bad.yaml"
    p.write_text(body)
    result = subprocess.run(
        [sys.executable, "-m", "engine.expedition_template", "validate", str(p)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "kind" in (result.stderr + result.stdout).lower()
