from __future__ import annotations

import enum

from pydantic_settings import BaseSettings


class Environment(str, enum.Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class Settings(BaseSettings):
    # Discord
    DISCORD_TOKEN: str = ""
    DISCORD_GUILD_ID: str = ""

    # Database — Railway injects this in production
    DATABASE_URL: str = "postgresql+asyncpg://dare2drive:dare2drive@db:5432/dare2drive"

    # Redis — Railway injects this in production
    REDIS_URL: str = "redis://redis:6379/0"

    # Infisical
    INFISICAL_TOKEN: str = ""
    INFISICAL_PROJECT_ID: str = ""
    INFISICAL_ENVIRONMENT: str = "dev"

    # App
    API_SECRET_KEY: str = "change-me"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "text"  # "text" | "json" — use "json" in production for Fluent Bit
    ENVIRONMENT: Environment = Environment.DEVELOPMENT

    # Monitoring — ntfy.sh push notifications (phone alerting)
    # Set NTFY_TOPIC to a private, hard-to-guess topic name so only your team receives alerts.
    # Team members install the free ntfy app (iOS / Android) and subscribe to this topic.
    NTFY_TOPIC: str = ""
    NTFY_URL: str = "https://ntfy.sh"  # self-hosted ntfy instance URL or ntfy.sh

    # Economy constants
    STARTING_CURRENCY: int = 0
    DAILY_MIN: int = 50
    DAILY_MAX: int = 150
    JUNKYARD_PACK_COST: int = 100
    PERFORMANCE_PACK_COST: int = 350
    LEGEND_CRATE_COST: int = 1200

    # Pack sizes
    JUNKYARD_PACK_SIZE: int = 3
    PERFORMANCE_PACK_SIZE: int = 3
    LEGEND_CRATE_SIZE: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def sync_database_url(self) -> str:
        """Return a synchronous database URL for Alembic."""
        return self.DATABASE_URL.replace("+asyncpg", "")


settings = Settings()
