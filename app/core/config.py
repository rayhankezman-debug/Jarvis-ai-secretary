"""
Application configuration using Pydantic Settings.

All configuration is loaded from environment variables (or .env file).
This is the SINGLE SOURCE OF TRUTH for all settings.

Why Pydantic Settings?
- Automatic type validation (catches bad config early)
- .env file support built-in
- Clear documentation of what env vars are needed
- No scattered os.getenv() calls throughout the codebase
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- Telegram ---
    telegram_bot_token: str = Field(
        default="",
        description="Telegram Bot API token from @BotFather",
    )

    # --- Gemini AI ---
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key",
    )
    gemini_model: str = Field(
        default="gemini-2.0-flash",
        description="Gemini model name to use",
    )

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://user:password@localhost:5432/ai_secretary",
        description="PostgreSQL connection string (async)",
    )

    # --- Morning Brief (Phase 7) ---
    morning_brief_time: str = Field(
        default="07:00",
        description="Time of day to send morning brief (HH:MM format)",
    )
    enable_morning_brief: bool = Field(
        default=True,
        description="Whether to enable automated morning brief delivery",
    )

    # --- Timezone ---
    timezone: str = Field(
        default="Asia/Jakarta",
        description="Default timezone for scheduling and display",
    )

    # --- Application ---
    app_env: str = Field(
        default="development",
        description="Environment: development, staging, production",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR",
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Singleton instance — import this throughout the app
settings = Settings()
