"""Tests for config/settings.py."""

from __future__ import annotations

from config.settings import Environment, Settings


class TestSettings:
    def test_default_values(self):
        s = Settings(
            DISCORD_TOKEN="test",
            DATABASE_URL="postgresql+asyncpg://localhost/test",
        )
        assert s.STARTING_CURRENCY == 0
        assert s.DAILY_MIN == 50
        assert s.DAILY_MAX == 150
        assert s.JUNKYARD_PACK_COST == 100
        assert s.PERFORMANCE_PACK_COST == 350
        assert s.LEGEND_CRATE_COST == 1200
        assert s.ENVIRONMENT == Environment.DEVELOPMENT

    def test_sync_database_url(self):
        s = Settings(DATABASE_URL="postgresql+asyncpg://localhost/test")
        assert s.sync_database_url == "postgresql://localhost/test"

    def test_environment_enum(self):
        assert Environment.DEVELOPMENT.value == "development"
        assert Environment.PRODUCTION.value == "production"

    def test_pack_sizes(self):
        s = Settings()
        assert s.JUNKYARD_PACK_SIZE == 3
        assert s.PERFORMANCE_PACK_SIZE == 3
        assert s.LEGEND_CRATE_SIZE == 3

    def test_phase2a_scheduler_settings_defaults(self):
        from config.settings import settings

        assert settings.SCHEDULER_TICK_INTERVAL_SECONDS == 5
        assert settings.SCHEDULER_BATCH_SIZE == 100
        assert settings.SCHEDULER_MAX_ATTEMPTS == 3
        assert settings.SCHEDULER_STUCK_CLAIM_TIMEOUT_SECS == 300
        assert settings.SCHEDULER_RECOVERY_INTERVAL_SECS == 60
        assert settings.ACCRUAL_TICK_INTERVAL_MINUTES == 30
        assert settings.ACCRUAL_NOTIFICATION_THRESHOLD == 1000
        assert settings.TIMER_CANCEL_REFUND_PCT == 50
        assert settings.NOTIFICATION_RATE_LIMIT_PER_HOUR == 5
        assert settings.NOTIFICATION_BATCH_WINDOW_SECONDS == 30
        assert settings.NOTIFICATION_STREAM_MAXLEN == 10000
