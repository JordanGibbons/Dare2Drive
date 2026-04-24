"""Tests for the audit_pivot script that flags car-vocabulary leaks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_audit_passes_on_clean_repo():
    """When no car-vocab leaks exist in player-facing files, the script exits 0."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "audit_pivot.py")],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        pytest.fail(f"Audit failed:\n{result.stdout}\n{result.stderr}")


def test_audit_fails_when_leak_introduced(tmp_path):
    """Adding a file with 'car' as a noun in a player-facing context fails the audit."""
    bad_file = tmp_path / "bot" / "cogs" / "leak.py"
    bad_file.parent.mkdir(parents=True)
    bad_file.write_text('MESSAGE = "Your car is ready"\n')

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "audit_pivot.py"),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "leak.py" in result.stdout or "leak.py" in result.stderr
