"""
Tests for Phase 0 — Foundation.

These tests verify:
1. The FastAPI app starts correctly
2. The health check endpoint works
3. Configuration loads properly
4. The LLM abstraction layer is structured correctly
"""

import pytest
from app.core.config import Settings
from app.ai.base import LLMProvider, LLMError, LLMRateLimitError


# ──────────────────────────────────────────────
# Health Check Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_returns_200(client):
    """Health endpoint should return 200 with status info."""
    response = await client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"
    assert "current_time" in data
    assert "timezone" in data


@pytest.mark.asyncio
async def test_health_check_shows_timezone(client):
    """Health endpoint should show the configured timezone."""
    response = await client.get("/health")
    data = response.json()
    assert data["timezone"] == "Asia/Jakarta"


# ──────────────────────────────────────────────
# Configuration Tests
# ──────────────────────────────────────────────

def test_settings_default_timezone():
    """Default timezone should be Asia/Jakarta."""
    s = Settings()
    assert s.timezone == "Asia/Jakarta"


def test_settings_default_model():
    """Default Gemini model should be set."""
    s = Settings(_env_file=None)
    assert s.gemini_model == "gemini-2.0-flash"


def test_settings_default_environment():
    """Default environment should be development."""
    s = Settings()
    assert s.app_env == "development"


# ──────────────────────────────────────────────
# LLM Abstraction Tests
# ──────────────────────────────────────────────

def test_llm_provider_is_abstract():
    """LLMProvider cannot be instantiated directly — it's abstract."""
    with pytest.raises(TypeError):
        LLMProvider()


def test_llm_error_includes_provider():
    """LLM errors should include the provider name."""
    error = LLMError("something failed", provider="gemini")
    assert "gemini" in str(error)
    assert error.provider == "gemini"


def test_llm_rate_limit_error_is_llm_error():
    """Rate limit error should be a subclass of LLMError."""
    error = LLMRateLimitError("rate limited", provider="gemini", retry_after=60.0)
    assert isinstance(error, LLMError)
    assert error.retry_after == 60.0


# ──────────────────────────────────────────────
# Logging Tests
# ──────────────────────────────────────────────

def test_sensitive_data_filter():
    """Sensitive data filter should redact API keys in log messages."""
    import logging
    from app.core.logging import SensitiveDataFilter

    f = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="Token is 123456789:ABCdefGHIjklMNOpqrSTUvwxYZ1234567890",
        args=(), exc_info=None,
    )
    f.filter(record)
    assert "[REDACTED]" in record.msg
    assert "123456789:ABCdef" not in record.msg
