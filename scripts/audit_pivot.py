#!/usr/bin/env python3
"""Audit script: fail if car-era vocabulary leaks into player-facing strings."""

from __future__ import annotations

import re
import sys
from pathlib import Path

LEAK_PATTERNS = [
    (re.compile(r"\bcar\b", re.IGNORECASE), "'car' as a noun"),
    (re.compile(r"\bautomobile\b", re.IGNORECASE), "'automobile'"),
    (re.compile(r"\bvehicle\b", re.IGNORECASE), "'vehicle' (use 'ship' instead)"),
    (re.compile(r"\brig\b"), "'rig' (use 'ship' or 'fleet' instead)"),
    (re.compile(r"\bbody_type\b"), "'body_type' (renamed to hull_class)"),
    (re.compile(r"\bcar_class\b"), "'car_class' (renamed to race_format)"),
]

OLD_SLOT_VALUES = ["engine", "transmission", "tires", "suspension", "chassis", "turbo", "brakes"]
SLOT_LEAK_PATTERN = re.compile(r'"(' + "|".join(OLD_SLOT_VALUES) + r')"')

SCAN_DIRS = ["bot/cogs", "data", "engine"]
EXCLUDE_NAME_PREFIXES = ("test_",)
EXCLUDE_NAMES = {"audit_pivot.py"}
EXCLUDE_PATH_PARTS = {"__pycache__", ".git"}


def should_scan(path: Path) -> bool:
    if path.name in EXCLUDE_NAMES or path.name.startswith(EXCLUDE_NAME_PREFIXES):
        return False
    return not any(part in EXCLUDE_PATH_PARTS for part in path.parts)


def scan_repo(root: Path) -> list[str]:
    """Return list of leak descriptions found."""
    leaks = []
    for scan_dir in SCAN_DIRS:
        d = root / scan_dir
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if not f.is_file() or not should_scan(f):
                continue
            if f.suffix not in {".py", ".json", ".md"}:
                continue
            try:
                content = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern, desc in LEAK_PATTERNS:
                for m in pattern.finditer(content):
                    line_no = content[: m.start()].count("\n") + 1
                    leaks.append(f"{f}:{line_no}: {desc}")
            for m in SLOT_LEAK_PATTERN.finditer(content):
                line_no = content[: m.start()].count("\n") + 1
                leaks.append(f"{f}:{line_no}: old slot value {m.group(0)}")
    return leaks


def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    leaks = scan_repo(root)
    if leaks:
        print("Pivot audit FAILED. Player-facing files contain car-era vocabulary:")
        for leak in leaks:
            print(f"  {leak}")
        sys.exit(1)
    print("Pivot audit passed. No car-era vocabulary leaks found.")
    sys.exit(0)


if __name__ == "__main__":
    main()
