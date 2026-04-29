"""HangarView — custom_id encoding/decoding tests."""

from __future__ import annotations

import uuid


def test_make_select_custom_id_format():
    from bot.views.hangar_view import make_select_custom_id

    build_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
    out = make_select_custom_id(build_id, "PILOT")
    assert out == "hangar:slot:12345678-1234-5678-1234-567812345678:PILOT"


def test_parse_select_custom_id_round_trip():
    from bot.views.hangar_view import make_select_custom_id, parse_select_custom_id

    build_id = uuid.uuid4()
    cid = make_select_custom_id(build_id, "GUNNER")
    parsed = parse_select_custom_id(cid)
    assert parsed == (build_id, "GUNNER")


def test_parse_select_custom_id_rejects_unknown_prefix():
    from bot.views.hangar_view import parse_select_custom_id

    assert parse_select_custom_id("expedition:button:foo:bar") is None
    assert parse_select_custom_id("totally bogus") is None
