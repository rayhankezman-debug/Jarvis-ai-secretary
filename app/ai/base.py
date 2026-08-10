"""
LLM Provider Abstraction Layer.

This is the interface that ALL LLM providers must implement.
The rest of the application imports ONLY this interface — never
a specific provider like Gemini directly.

Why an abstraction layer?
- Swap AI providers without changing business logic
- Test with mock providers
- Support multiple providers simultaneously in the future

Architecture:
    LLMProvider (this file — abstract interface)
        ├── GeminiProvider (Phase 3)
        ├── OpenAIProvider (future)
        └── MockProvider   (testing)
"""

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    Every AI provider (Gemini, OpenAI, local models, etc.)
    must implement these methods.
    """

    @abstractmethod
    async def generate_structured_response(
        self,
        prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate a structured (JSON) response from the LLM.

        This is the PRIMARY method used for task extraction and intent detection.
        The LLM should return data matching the provided schema.

        Args:
            prompt: The user message + system instructions.
            response_schema: Optional JSON schema the response should conform to.

        Returns:
            Parsed dictionary matching the expected structure.

        Raises:
            LLMError: If the API call fails or response is invalid.
        """
        ...

    @abstractmethod
    async def generate_text(self, prompt: str) -> str:
        """
        Generate a free-form text response.

        Used for conversational replies, daily plan descriptions, etc.

        Args:
            prompt: The input prompt.

        Returns:
            Generated text string.

        Raises:
            LLMError: If the API call fails.
        """
        ...


class LLMError(Exception):
    """Base exception for LLM provider errors."""

    def __init__(self, message: str, provider: str = "unknown", retry_after: float | None = None):
        self.provider = provider
        self.retry_after = retry_after
        super().__init__(f"[{provider}] {message}")


class LLMRateLimitError(LLMError):
    """Raised when the API rate limit is exceeded."""
    pass


class LLMInvalidResponseError(LLMError):
    """Raised when the LLM returns an unparseable or invalid response."""
    pass
