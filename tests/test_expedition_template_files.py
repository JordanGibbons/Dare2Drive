"""CI gate: every committed template must validate."""

from __future__ import annotations

from pathlib import Path

import pytest

_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "expeditions"


def test_at_least_two_templates_committed():
    yamls = list(_DATA_DIR.glob("*.yaml"))
    assert len(yamls) >= 2, f"v1 ships with at least 2 templates; found {len(yamls)}"


@pytest.mark.parametrize("path", sorted(_DATA_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_template_validates(path):
    from engine.expedition_template import load_template_file

    load_template_file(path)
