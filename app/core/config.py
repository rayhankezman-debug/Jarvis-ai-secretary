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
from pydantic import Field, field_validator


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

    # --- Evening Review (Phase 8) ---
    evening_review_time: str = Field(
        default="20:00",
        description="Time of day to send evening review (HH:MM format)",
    )
    enable_evening_review: bool = Field(
        default=True,
        description="Whether to enable automated evening review delivery",
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

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(v)
        except Exception as e:
            raise ValueError(f"Invalid timezone configuration '{v}': {e}")
        return v

    @field_validator("morning_brief_time", "evening_review_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        try:
            parts = v.strip().split(":")
            if len(parts) != 2:
                raise ValueError()
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError()
        except Exception:
            raise ValueError(f"Invalid time format '{v}'. Expected 'HH:MM' (00:00 - 23:59).")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Invalid log_level '{v}'. Must be one of {valid_levels}")
        return v.upper()

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Singleton instance — import this throughout the app
settings = Settings()
