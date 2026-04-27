"""Tests for api/metrics.py — custom Prometheus counters and histograms."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY, Counter, Gauge, Histogram


class TestMetricsExist:
    """Verify all expected metric objects are importable and have correct types."""

    def test_races_started_is_counter(self):
        from api.metrics import races_started

        assert isinstance(races_started, Counter)

    def test_races_completed_is_counter(self):
        from api.metrics import races_completed

        assert isinstance(races_completed, Counter)

    def test_packs_opened_is_counter(self):
        from api.metrics import packs_opened

        assert isinstance(packs_opened, Counter)

    def test_daily_claimed_is_counter(self):
        from api.metrics import daily_claimed

        assert isinstance(daily_claimed, Counter)

    def test_currency_spent_is_counter(self):
        from api.metrics import currency_spent

        assert isinstance(currency_spent, Counter)

    def test_users_registered_is_gauge(self):
        from api.metrics import users_registered

        assert isinstance(users_registered, Gauge)

    def test_parts_destroyed_is_counter(self):
        from api.metrics import parts_destroyed

        assert isinstance(parts_destroyed, Counter)

    def test_bot_commands_invoked_is_counter(self):
        from api.metrics import bot_commands_invoked

        assert isinstance(bot_commands_invoked, Counter)

    def test_bot_command_errors_is_counter(self):
        from api.metrics import bot_command_errors

        assert isinstance(bot_command_errors, Counter)

    def test_api_request_duration_is_histogram(self):
        from api.metrics import api_request_duration_seconds

        assert isinstance(api_request_duration_seconds, Histogram)


class TestMetricLabels:
    """Verify metrics accept the expected label sets without raising."""

    def test_races_started_labels(self):
        from api.metrics import races_started

        races_started.labels(race_type="tutorial").inc(0)
        races_started.labels(race_type="open").inc(0)

    def test_races_completed_labels(self):
        from api.metrics import races_completed

        races_completed.labels(race_type="open", outcome="win").inc(0)
        races_completed.labels(race_type="open", outcome="loss").inc(0)
        races_completed.labels(race_type="open", outcome="wreck").inc(0)

    def test_packs_opened_labels(self):
        from api.metrics import packs_opened

        packs_opened.labels(pack_type="salvage_crate").inc(0)
        packs_opened.labels(pack_type="gear_crate").inc(0)
        packs_opened.labels(pack_type="legend_crate").inc(0)

    def test_currency_spent_labels(self):
        from api.metrics import currency_spent

        currency_spent.labels(reason="salvage_crate").inc(0)
        currency_spent.labels(reason="new_build").inc(0)

    def test_parts_destroyed_labels(self):
        from api.metrics import parts_destroyed

        parts_destroyed.labels(reason="wear").inc(0)
        parts_destroyed.labels(reason="wreck").inc(0)

    def test_bot_commands_invoked_labels(self):
        from api.metrics import bot_commands_invoked

        bot_commands_invoked.labels(command="race").inc(0)
        bot_commands_invoked.labels(command="pack").inc(0)


class TestMetricsRegistered:
    """Verify that all metrics are registered in the default Prometheus registry."""

    @pytest.mark.parametrize(
        "metric_name",
        [
            "dare2drive_races_started",
            "dare2drive_races_completed",
            "dare2drive_packs_opened",
            "dare2drive_daily_claimed",
            "dare2drive_currency_spent",
            "dare2drive_users_registered_total",
            "dare2drive_parts_destroyed",
            "dare2drive_bot_commands",
            "dare2drive_bot_command_errors",
            "dare2drive_api_request_duration_seconds",
        ],
    )
    def test_metric_in_registry(self, metric_name: str):
        import api.metrics  # noqa: F401 — ensure module is imported so metrics register

        names = {m.name for m in REGISTRY.collect()}
        assert metric_name in names, f"{metric_name} not found in Prometheus registry"


class TestMetricsEndpoint:
    """Integration test: /metrics endpoint returns Prometheus text format."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint_returns_200(self):
        from httpx import ASGITransport, AsyncClient

        from api.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics")

        assert resp.status_code == 200
        assert "dare2drive_races_started_total" in resp.text

    @pytest.mark.asyncio
    async def test_metrics_content_type(self):
        from httpx import ASGITransport, AsyncClient

        from api.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics")

        assert "application/openmetrics-text" in resp.headers.get("content-type", "")


def test_phase2b_metrics_exist():
    from api.metrics import (
        expedition_active,
        expedition_event_response_seconds,
        expedition_events_fired_total,
        expedition_events_resolved_total,
        expeditions_completed_total,
        expeditions_started_total,
    )

    expeditions_started_total.labels(template_id="x", kind="rolled").inc(0)
    expeditions_completed_total.labels(template_id="x", outcome="success").inc(0)
    expedition_events_fired_total.labels(template_id="x", scene_id="y").inc(0)
    expedition_events_resolved_total.labels(template_id="x", scene_id="y", source="auto").inc(0)
    expedition_active.set(0)
    expedition_event_response_seconds.labels(template_id="x").observe(0.0)
