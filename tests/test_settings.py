"""Tests for config/settings.py."""

from __future__ import annotations

from config.settings import Environment, Settings


class TestSettings:
    def test_default_values(self):
        s = Settings(
            DISCORD_TOKEN="test",
            DATABASE_URL="postgresql+asyncpg://localhost/test",
        )
        assert s.STARTING_CURRENCY == 500
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
