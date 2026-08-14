"""
AI services package — LLM provider abstraction and implementations.

Public API:
    LLMProvider           — Abstract base class (interface)
    LLMError              — Base LLM exception
    LLMRateLimitError     — Rate limit exception
    LLMInvalidResponseError — Invalid response exception
    GeminiProvider        — Google Gemini implementation
    get_llm_provider      — Factory function to get the configured provider
"""

from app.ai.base import (
    LLMError,
    LLMInvalidResponseError,
    LLMProvider,
    LLMRateLimitError,
)
from app.ai.gemini import GeminiProvider
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level cached provider instance
_provider_instance: LLMProvider | None = None


def get_llm_provider() -> LLMProvider | None:
    """
    Get the configured LLM provider instance (singleton).

    Returns the cached provider if already created, or creates
    a new one based on the current settings.

    Returns:
        LLMProvider instance, or None if no API key is configured.

    Why a factory function?
    - Lazy initialization (don't create client until needed)
    - Centralized provider selection (swap providers here)
    - Singleton pattern (reuse the same client across requests)
    """
    global _provider_instance

    if _provider_instance is not None:
        return _provider_instance

    if not settings.gemini_api_key:
        logger.warning(
            "GEMINI_API_KEY not set — AI features disabled. "
            "Set it in .env to enable Gemini AI."
        )
        return None

    try:
        _provider_instance = GeminiProvider()
        return _provider_instance
    except Exception as e:
        logger.error(f"Failed to create LLM provider: {e}")
        return None


def reset_provider() -> None:
    """Reset the cached provider instance. Used in testing."""
    global _provider_instance
    _provider_instance = None


__all__ = [
    "LLMProvider",
    "LLMError",
    "LLMRateLimitError",
    "LLMInvalidResponseError",
    "GeminiProvider",
    "get_llm_provider",
    "reset_provider",
]
