"""Regenerate the auto-managed reference tables in docs/authoring/expeditions.md.

The guide has two markers:

    <!-- BEGIN: STAT_NAMESPACE_TABLE -->
    ...auto-generated table...
    <!-- END: STAT_NAMESPACE_TABLE -->

    <!-- BEGIN: EFFECT_VOCABULARY_TABLE -->
    ...auto-generated table...
    <!-- END: EFFECT_VOCABULARY_TABLE -->

This script reads engine.stat_namespace.KNOWN_STAT_KEYS + archetype_for_stat
and engine.effect_registry.KNOWN_OPS, formats them as Markdown tables, and
rewrites the regions in-place.

CI runs this and fails if `git diff` is non-empty (i.e., the committed guide
is stale). Authors who change the engine registries must re-run this script
and commit the regenerated guide as part of the same PR.

Usage:
    python -m scripts.build_authoring_docs           # rewrites in place
    python -m scripts.build_authoring_docs --check   # exit 1 if dirty
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from engine.effect_registry import KNOWN_OPS
from engine.stat_namespace import KNOWN_STAT_KEYS, archetype_for_stat

_GUIDE = Path(__file__).resolve().parents[1] / "docs" / "authoring" / "expeditions.md"


def _stat_table() -> str:
    rows = ["| Key | Implicit archetype gate | Source |", "|---|---|---|"]
    for key in sorted(KNOWN_STAT_KEYS):
        gate = archetype_for_stat(key) or "—"
        if key.startswith("ship."):
            source = "resolved live from the locked build (engine/stat_resolver)"
        elif key.startswith("crew."):
            source = "aggregate across all assigned crew"
        else:
            source = f"the assigned {gate} crew member's stats"
        rows.append(f"| `{key}` | {gate} | {source} |")
    return "\n".join(rows)


def _effect_table() -> str:
    rows = ["| Op | Required params | Summary |", "|---|---|---|"]
    for name in sorted(KNOWN_OPS):
        spec = KNOWN_OPS[name]
        if spec["param_kind"] == "scalar_int":
            params = "(int value)"
        else:
            params = ", ".join(f"`{p}`" for p in spec["params"]) or "—"
        rows.append(f"| `{name}` | {params} | {spec['summary']} |")
    return "\n".join(rows)


_REGIONS = [
    ("STAT_NAMESPACE_TABLE", _stat_table),
    ("EFFECT_VOCABULARY_TABLE", _effect_table),
]


def regenerate(text: str) -> str:
    out = text
    for marker, builder in _REGIONS:
        pattern = re.compile(
            rf"(<!-- BEGIN: {marker} -->\n).*?(\n<!-- END: {marker} -->)",
            re.DOTALL,
        )
        replacement = rf"\g<1>{builder()}\g<2>"
        new_out, n = pattern.subn(replacement, out)
        if n != 1:
            raise RuntimeError(f"Marker {marker} not found exactly once in {_GUIDE}")
        out = new_out
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="Exit non-zero if the file is out of date"
    )
    args = parser.parse_args(argv)

    original = _GUIDE.read_text(encoding="utf-8")
    new_content = regenerate(original)

    if args.check:
        if new_content != original:
            print("docs/authoring/expeditions.md is out of date.", file=sys.stderr)
            print("Run `python -m scripts.build_authoring_docs` and commit.", file=sys.stderr)
            return 1
        return 0

    if new_content != original:
        _GUIDE.write_text(new_content, encoding="utf-8")
        print(f"Regenerated {_GUIDE}")
    else:
        print(f"{_GUIDE} already up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
