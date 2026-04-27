"""Expedition template loader, JSON Schema + semantic validator, CLI entry point.

Public API:
    load_template_file(path) -> dict   # validate + parse one file
    load_template(template_id) -> dict # by id from data/expeditions/
    validate_all() -> None             # iterate data/expeditions/*.yaml
    main()                             # CLI: python -m engine.expedition_template

Validator runs four passes:
    1. JSON Schema conformance (data/expeditions/schema.json)
    2. Filename matches id
    3. Choice / closing / pool semantic invariants
    4. Stat namespace + effect vocabulary + archetype + flag cross-refs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import jsonschema
import yaml

from db.models import CrewArchetype
from engine.effect_registry import validate_effect
from engine.stat_namespace import is_known_stat

_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "expeditions"
_SCHEMA_PATH = _DATA_DIR / "schema.json"


class TemplateValidationError(ValueError):
    """Raised when a template fails any validation pass."""


def _load_schema() -> dict[str, Any]:
    with _SCHEMA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


_SCHEMA = _load_schema()


def load_template_file(path: Path | str) -> dict[str, Any]:
    """Load + validate a single template file. Raises TemplateValidationError on issues."""
    p = Path(path)
    if not p.exists():
        raise TemplateValidationError(f"file not found: {p}")
    with p.open(encoding="utf-8") as f:
        try:
            doc = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise TemplateValidationError(f"YAML parse error in {p}: {e}") from e

    if not isinstance(doc, dict):
        raise TemplateValidationError(f"top-level YAML must be a mapping in {p}")

    # 1. JSON Schema
    try:
        jsonschema.validate(doc, _SCHEMA)
    except jsonschema.ValidationError as e:
        raise TemplateValidationError(f"schema error in {p}: {e.message}") from e

    # 2. Filename matches id
    if doc["id"] != p.stem:
        raise TemplateValidationError(
            f"filename must match id in {p}: file says {p.stem}, doc says {doc['id']}"
        )

    # 3 + 4. Semantic checks
    errors = list(_semantic_errors(doc))
    if errors:
        raise TemplateValidationError(
            f"semantic errors in {p}:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return doc


def load_template(template_id: str) -> dict[str, Any]:
    """Load + validate a template by id from data/expeditions/."""
    return load_template_file(_DATA_DIR / f"{template_id}.yaml")


def validate_all() -> None:
    """Iterate every data/expeditions/*.yaml and validate. Raises on first failure."""
    for path in sorted(_DATA_DIR.glob("*.yaml")):
        load_template_file(path)


def _semantic_errors(doc: dict[str, Any]) -> Iterable[str]:
    """Yield semantic-validation error strings."""
    kind = doc["kind"]

    # Walk all scenes (kind-specific) — emit generic checks per scene with choices.
    scenes = list(_iter_scenes(doc))
    for scene in scenes:
        if "choices" in scene:
            yield from _check_scene_choices(scene)

    # Closing check (both kinds): exactly one default.
    closings = _all_closings(doc)
    defaults = [c for c in closings if c.get("when", {}).get("default") is True]
    if len(defaults) != 1:
        yield (f"every template must have exactly one default closing — " f"found {len(defaults)}")

    # Rolled-template-specific
    if kind == "rolled":
        ec = doc.get("event_count", 0)
        ev = doc.get("events", [])
        if len(ev) < ec:
            yield (
                f"rolled template event_count={ec} but pool has only {len(ev)} events; "
                "increase pool or lower event_count"
            )

    # Stat / effect / archetype / flag cross-refs
    set_flag_names: set[str] = set()
    yield from _walk_effects(doc, set_flag_names)
    yield from _check_flag_references(doc, set_flag_names)
    yield from _check_stat_references(doc)
    yield from _check_archetype_references(doc)


def _iter_scenes(doc: dict[str, Any]) -> Iterable[dict[str, Any]]:
    if doc["kind"] == "scripted":
        yield from doc.get("scenes", [])
    else:
        yield doc.get("opening", {})
        yield from doc.get("events", [])


def _all_closings(doc: dict[str, Any]) -> list[dict[str, Any]]:
    if doc["kind"] == "scripted":
        out: list[dict[str, Any]] = []
        for scene in doc.get("scenes", []):
            if scene.get("is_closing"):
                out.extend(scene.get("closings", []))
        return out
    return list(doc.get("closings", []))


def _check_scene_choices(scene: dict[str, Any]) -> Iterable[str]:
    choices = scene.get("choices", [])
    defaults = [c for c in choices if c.get("default")]
    if len(defaults) != 1:
        yield (
            f"scene `{scene.get('id')}` must have exactly one default choice — "
            f"found {len(defaults)}"
        )
    for c in defaults:
        if "requires" in c:
            yield (
                f"scene `{scene.get('id')}` default choice `{c.get('id')}` "
                "must NOT have `requires` (default must always be available)"
            )


def _walk_effects(doc: dict[str, Any], set_flag_names: set[str]) -> Iterable[str]:
    """Validate every effect op + collect set_flag names."""
    for source, effects in _iter_all_effects(doc):
        for eff in effects:
            errors = validate_effect(eff)
            for e in errors:
                yield f"{source}: {e}"
            if isinstance(eff, dict) and "set_flag" in eff:
                v = eff["set_flag"]
                if isinstance(v, dict) and "name" in v:
                    set_flag_names.add(v["name"])


def _iter_all_effects(doc: dict[str, Any]) -> Iterable[tuple[str, list[dict]]]:
    for scene in _iter_scenes(doc):
        sid = scene.get("id", "?")
        for choice in scene.get("choices", []):
            cid = choice.get("id", "?")
            for outcome_key, outcome in (choice.get("outcomes") or {}).items():
                if outcome and "effects" in outcome:
                    yield (f"scene {sid}/choice {cid}/{outcome_key}", outcome["effects"])
    for closing in _all_closings(doc):
        yield ("closing", closing.get("effects", []))


def _check_flag_references(doc: dict[str, Any], set_flag_names: set[str]) -> Iterable[str]:
    for closing in _all_closings(doc):
        when = closing.get("when") or {}
        for key in ("has_flag", "not_flag"):
            ref = when.get(key)
            if ref and ref not in set_flag_names:
                yield (
                    f"closing references {key}={ref!r} but no scene sets that flag — "
                    "typo or unreachable variant"
                )


def _check_stat_references(doc: dict[str, Any]) -> Iterable[str]:
    for scene in _iter_scenes(doc):
        for choice in scene.get("choices", []):
            roll = choice.get("roll")
            if roll and not is_known_stat(roll["stat"]):
                yield (
                    f"scene {scene.get('id')}/choice {choice.get('id')}: "
                    f"unknown stat {roll['stat']!r}"
                )


def _check_archetype_references(doc: dict[str, Any]) -> Iterable[str]:
    valid = {a.value for a in CrewArchetype} | {a.value.upper() for a in CrewArchetype}
    valid |= {"PILOT", "GUNNER", "ENGINEER", "NAVIGATOR"}
    crew_req = doc.get("crew_required") or {}
    for key in ("archetypes_any", "archetypes_all"):
        for a in crew_req.get(key, []) or []:
            if a not in valid:
                yield f"crew_required.{key}: unknown archetype {a!r}"
    for scene in _iter_scenes(doc):
        for choice in scene.get("choices", []):
            req = choice.get("requires") or {}
            if "archetype" in req and req["archetype"] not in valid:
                yield f"choice {choice.get('id')}: unknown archetype {req['archetype']!r}"
            for outcome_key, outcome in (choice.get("outcomes") or {}).items():
                for eff in (outcome or {}).get("effects", []) or []:
                    if not isinstance(eff, dict):
                        continue
                    for op in ("reward_xp", "injure_crew"):
                        if op in eff and isinstance(eff[op], dict):
                            a = eff[op].get("archetype")
                            if a is not None and a not in valid:
                                yield (
                                    f"choice {choice.get('id')}/{outcome_key}/{op}: "
                                    f"unknown archetype {a!r}"
                                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine.expedition_template")
    sub = parser.add_subparsers(dest="cmd", required=True)
    val = sub.add_parser("validate", help="Validate one or more template files")
    val.add_argument("paths", nargs="+", help="Paths to YAML files (or directory)")
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        rc = 0
        for raw in args.paths:
            p = Path(raw)
            targets = list(p.glob("*.yaml")) if p.is_dir() else [p]
            for t in targets:
                try:
                    load_template_file(t)
                    print(f"OK  {t}")
                except TemplateValidationError as e:
                    print(f"FAIL {t}: {e}", file=sys.stderr)
                    rc = 1
        return rc
    return 2


if __name__ == "__main__":
    sys.exit(main())
