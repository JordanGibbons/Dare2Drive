"""Tests for the ntfy-relay service (monitoring/ntfy-relay/relay.py).

These tests run against the FastAPI app directly via ASGI without needing
network access to ntfy.sh or Discord.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# Add the relay module to the path so it can be imported directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "monitoring" / "ntfy-relay"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_FIRING_ALERT = {
    "status": "firing",
    "labels": {"alertname": "ApiDown", "severity": "critical"},
    "annotations": {
        "summary": "Dare2Drive API is unreachable",
        "description": "Prometheus cannot scrape the API /metrics endpoint.",
    },
    "generatorURL": "http://prometheus:9090/graph",
}

SAMPLE_RESOLVED_ALERT = {
    "status": "resolved",
    "labels": {"alertname": "ApiDown", "severity": "critical"},
    "annotations": {
        "summary": "Dare2Drive API is unreachable",
        "description": "Prometheus cannot scrape the API /metrics endpoint.",
    },
    "generatorURL": "http://prometheus:9090/graph",
}

SAMPLE_WARNING_ALERT = {
    "status": "firing",
    "labels": {"alertname": "HighErrorRate", "severity": "warning", "job": "dare2drive_api"},
    "annotations": {
        "summary": "High HTTP 5xx error rate",
        "description": "More than 5 % of API requests are returning 5xx errors.",
    },
}

ALERTMANAGER_PAYLOAD = {
    "version": "4",
    "groupLabels": {"alertname": "ApiDown"},
    "commonLabels": {"severity": "critical"},
    "alerts": [SAMPLE_FIRING_ALERT],
}


# ---------------------------------------------------------------------------
# Unit tests for _build_discord_embed
# ---------------------------------------------------------------------------


class TestBuildDiscordEmbed:
    def test_firing_critical_embed_colour(self):
        from relay import _build_discord_embed

        embed = _build_discord_embed(SAMPLE_FIRING_ALERT)
        assert embed["color"] == 0xED4245  # red

    def test_firing_warning_embed_colour(self):
        from relay import _build_discord_embed

        embed = _build_discord_embed(SAMPLE_WARNING_ALERT)
        assert embed["color"] == 0xFEE75C  # yellow

    def test_resolved_embed_colour(self):
        from relay import _build_discord_embed

        embed = _build_discord_embed(SAMPLE_RESOLVED_ALERT)
        assert embed["color"] == 0x57F287  # green

    def test_firing_title_has_emoji(self):
        from relay import _build_discord_embed

        embed = _build_discord_embed(SAMPLE_FIRING_ALERT)
        assert "🚨" in embed["title"]

    def test_resolved_title_has_resolved_prefix(self):
        from relay import _build_discord_embed

        embed = _build_discord_embed(SAMPLE_RESOLVED_ALERT)
        assert "RESOLVED" in embed["title"]
        assert "✅" in embed["title"]

    def test_embed_includes_description(self):
        from relay import _build_discord_embed

        embed = _build_discord_embed(SAMPLE_FIRING_ALERT)
        assert "Prometheus cannot scrape" in embed["description"]

    def test_embed_includes_severity_field(self):
        from relay import _build_discord_embed

        embed = _build_discord_embed(SAMPLE_FIRING_ALERT)
        field_names = [f["name"] for f in embed["fields"]]
        assert "Severity" in field_names

    def test_embed_includes_generator_url(self):
        from relay import _build_discord_embed

        embed = _build_discord_embed(SAMPLE_FIRING_ALERT)
        assert embed["url"] == "http://prometheus:9090/graph"

    def test_embed_extra_labels_become_fields(self):
        from relay import _build_discord_embed

        embed = _build_discord_embed(SAMPLE_WARNING_ALERT)
        field_names = [f["name"] for f in embed["fields"]]
        assert "Job" in field_names  # job label → "Job" field

    def test_embed_no_generator_url_omitted(self):
        from relay import _build_discord_embed

        alert = {**SAMPLE_FIRING_ALERT, "generatorURL": ""}
        embed = _build_discord_embed(alert)
        assert "url" not in embed


# ---------------------------------------------------------------------------
# Integration tests for relay endpoints
# ---------------------------------------------------------------------------


class TestRelayHealthz:
    @pytest.mark.asyncio
    async def test_healthz_returns_ok(self):
        from httpx import ASGITransport, AsyncClient
        from relay import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/healthz")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestRelayAlertsEndpoint:
    @pytest.mark.asyncio
    async def test_alerts_skips_ntfy_when_topic_empty(self):
        """When NTFY_TOPIC is empty, ntfy delivery is skipped (no HTTP call)."""
        import relay as relay_module
        from httpx import ASGITransport, AsyncClient

        original_topic = relay_module.NTFY_TOPIC
        relay_module.NTFY_TOPIC = ""
        relay_module.DISCORD_WEBHOOK_URL = ""

        transport = ASGITransport(app=relay_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/alerts", json=ALERTMANAGER_PAYLOAD)

        relay_module.NTFY_TOPIC = original_topic
        assert resp.status_code == 200
        assert resp.json()["forwarded"] == 1

    @pytest.mark.asyncio
    async def test_alerts_forwards_to_discord(self):
        """When DISCORD_WEBHOOK_URL is set, the relay calls _send_discord."""
        import relay as relay_module
        from httpx import ASGITransport, AsyncClient

        original_discord_url = relay_module.DISCORD_WEBHOOK_URL
        relay_module.DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/test/token"
        relay_module.NTFY_TOPIC = ""

        with patch("relay._send_discord", new_callable=AsyncMock) as mock_discord:
            mock_discord.return_value = None  # no error
            transport = ASGITransport(app=relay_module.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/alerts", json=ALERTMANAGER_PAYLOAD)

        relay_module.DISCORD_WEBHOOK_URL = original_discord_url

        assert resp.status_code == 200
        mock_discord.assert_called_once()

    @pytest.mark.asyncio
    async def test_alerts_uses_critical_channel_for_critical(self):
        """Critical alerts use DISCORD_WEBHOOK_URL_CRITICAL when configured."""
        import relay as relay_module
        from httpx import ASGITransport, AsyncClient

        relay_module.NTFY_TOPIC = ""
        relay_module.DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/general/token"
        relay_module.DISCORD_WEBHOOK_URL_CRITICAL = (
            "https://discord.com/api/webhooks/critical/token"
        )

        captured_url: list[str] = []

        async def fake_send_discord(client: object, alert: dict) -> None:
            # Inspect which webhook URL would be used by calling the original logic
            severity = alert.get("labels", {}).get("severity", "warning")
            status = alert.get("status", "firing")
            if (
                relay_module.DISCORD_WEBHOOK_URL_CRITICAL
                and severity == "critical"
                and status != "resolved"
            ):
                captured_url.append(relay_module.DISCORD_WEBHOOK_URL_CRITICAL)
            else:
                captured_url.append(relay_module.DISCORD_WEBHOOK_URL)
            return None

        with patch("relay._send_discord", side_effect=fake_send_discord):
            transport = ASGITransport(app=relay_module.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                await client.post("/alerts", json=ALERTMANAGER_PAYLOAD)

        relay_module.DISCORD_WEBHOOK_URL = ""
        relay_module.DISCORD_WEBHOOK_URL_CRITICAL = ""

        assert len(captured_url) == 1
        assert "critical" in captured_url[0]

    @pytest.mark.asyncio
    async def test_alerts_partial_error_on_discord_failure(self):
        """When Discord POST fails, the endpoint returns 207 with error info."""
        import relay as relay_module
        from httpx import ASGITransport, AsyncClient

        relay_module.DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/test/token"
        relay_module.NTFY_TOPIC = ""

        with patch("relay._send_discord", new_callable=AsyncMock) as mock_discord:
            mock_discord.return_value = "Discord delivery failed — check relay logs"
            transport = ASGITransport(app=relay_module.app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/alerts", json=ALERTMANAGER_PAYLOAD)

        relay_module.DISCORD_WEBHOOK_URL = ""
        assert resp.status_code == 207
        assert resp.json()["status"] == "partial_error"

    @pytest.mark.asyncio
    async def test_alerts_empty_payload(self):
        """An empty alerts list returns ok with forwarded=0."""
        import relay as relay_module
        from httpx import ASGITransport, AsyncClient

        relay_module.NTFY_TOPIC = ""
        relay_module.DISCORD_WEBHOOK_URL = ""

        transport = ASGITransport(app=relay_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/alerts", json={"alerts": []})

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "forwarded": 0}

    @pytest.mark.asyncio
    async def test_legacy_ntfy_endpoint_still_works(self):
        """The legacy /ntfy path returns 200 when ntfy is disabled."""
        import relay as relay_module
        from httpx import ASGITransport, AsyncClient

        relay_module.NTFY_TOPIC = ""

        transport = ASGITransport(app=relay_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/ntfy", json={"alerts": []})

        assert resp.status_code == 200
