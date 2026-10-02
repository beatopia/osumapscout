"""Environment-backed deployment configuration."""

import os
from dataclasses import dataclass

from backend.app.database.connection import get_database_url
from backend.app.osu.client import OsuCredentials

DEFAULT_LOCAL_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


@dataclass(frozen=True)
class AppConfig:
    cors_origins: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> "AppConfig":
        configured = os.getenv("CORS_ORIGINS", "").strip()
        origins = (
            tuple(item.strip() for item in configured.split(",") if item.strip())
            if configured
            else DEFAULT_LOCAL_ORIGINS
        )
        if any(origin == "*" for origin in origins):
            raise ValueError("CORS_ORIGINS must list explicit origins, not '*'.")
        return cls(origins)


def validate_server_environment() -> AppConfig:
    """Validate required configuration without contacting external services."""
    OsuCredentials.from_environment()
    get_database_url()
    return AppConfig.from_environment()
