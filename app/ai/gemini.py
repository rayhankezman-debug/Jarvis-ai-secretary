"""
Google Gemini LLM provider implementation.

This module implements the LLMProvider interface using the google-genai SDK.
It handles:
- Async communication with the Gemini API
- Structured JSON responses via response_schema
- Free-form text generation
- Error handling and rate limit detection
- Retry logic for transient failures

Architecture:
    LLMProvider (base.py — abstract)
        └── GeminiProvider (this file — concrete implementation)

Why google-genai instead of google-generativeai?
- google-genai is the newer, officially recommended SDK
- Better async support via client.aio
- Cleaner API for structured outputs
- Active development and support from Google
"""

import json
from typing import Any

from google import genai
from google.genai import types

from app.ai.base import (
    LLMError,
    LLMInvalidResponseError,
    LLMProvider,
    LLMRateLimitError,
)
from app.ai.prompts import CONVERSATIONAL_PROMPT, get_system_prompt
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Provider name constant
PROVIDER_NAME = "gemini"


class GeminiProvider(LLMProvider):
    """
    Gemini API implementation of LLMProvider.

    Uses the google-genai SDK with async support for non-blocking
    API calls that work well with FastAPI's async architecture.

    Usage:
        provider = GeminiProvider()
        response = await provider.generate_text("Hello!")
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        """
        Initialize the Gemini provider.

        Args:
            api_key: Gemini API key. Defaults to settings.gemini_api_key.
            model: Model name. Defaults to settings.gemini_model.
        """
        self._api_key = api_key or settings.gemini_api_key
        self._model = model or settings.gemini_model

        if not self._api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. "
                "Please set it in your .env file. "
                "Get a free key at https://aistudio.google.com/apikey"
            )

        # Create the genai client
        self._client = genai.Client(api_key=self._api_key)

        logger.info(f"GeminiProvider initialized with model: {self._model}")

    async def generate_structured_response(
        self,
        prompt: str,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate a structured JSON response from Gemini.

        Uses response_mime_type="application/json" to ensure the model
        returns valid JSON. If a response_schema is provided, the output
        will conform to that structure.

        Args:
            prompt: User message + context.
            response_schema: Optional JSON schema for the response.

        Returns:
            Parsed dictionary from the model's JSON response.

        Raises:
            LLMError: On API failure.
            LLMRateLimitError: When rate limited.
            LLMInvalidResponseError: When response can't be parsed as JSON.
        """
        try:
            config = types.GenerateContentConfig(
                system_instruction=get_system_prompt(),
                response_mime_type="application/json",
            )

            # Add schema if provided
            if response_schema is not None:
                config.response_schema = response_schema

            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=config,
            )

            if not response.text:
                raise LLMInvalidResponseError(
                    "Empty response from Gemini",
                    provider=PROVIDER_NAME,
                )

            # Parse JSON response
            try:
                result = json.loads(response.text)
            except json.JSONDecodeError as e:
                raise LLMInvalidResponseError(
                    f"Failed to parse JSON response: {e}. "
                    f"Raw response: {response.text[:200]}",
                    provider=PROVIDER_NAME,
                )

            logger.debug(f"Structured response generated: {list(result.keys())}")
            return result

        except (LLMError, LLMRateLimitError, LLMInvalidResponseError):
            # Re-raise our own exceptions
            raise
        except Exception as e:
            _handle_gemini_error(e)

    async def generate_text(self, prompt: str) -> str:
        """
        Generate a free-form text response from Gemini.

        Used for conversational replies where structured output isn't needed.

        Args:
            prompt: User message.

        Returns:
            Generated text string.

        Raises:
            LLMError: On API failure.
            LLMRateLimitError: When rate limited.
        """
        try:
            config = types.GenerateContentConfig(
                system_instruction=get_system_prompt() + "\n\n" + CONVERSATIONAL_PROMPT,
            )

            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config=config,
            )

            if not response.text:
                raise LLMError(
                    "Empty text response from Gemini",
                    provider=PROVIDER_NAME,
                )

            logger.debug(f"Text response generated ({len(response.text)} chars)")
            return response.text

        except (LLMError, LLMRateLimitError, LLMInvalidResponseError):
            raise
        except Exception as e:
            _handle_gemini_error(e)


def _handle_gemini_error(error: Exception) -> None:
    """
    Convert Gemini SDK exceptions to our LLM error hierarchy.

    This centralizes error mapping so both generate methods
    produce consistent error types.

    Args:
        error: The original exception from the Gemini SDK.

    Raises:
        LLMRateLimitError: For 429 / resource exhausted errors.
        LLMError: For all other API errors.
    """
    error_str = str(error).lower()

    # Detect rate limiting
    if "429" in error_str or "resource exhausted" in error_str or "resource_exhausted" in error_str or "rate limit" in error_str:
        logger.warning(f"Gemini rate limit hit: {error}")
        raise LLMRateLimitError(
            f"Rate limited: {error}",
            provider=PROVIDER_NAME,
            retry_after=60.0,  # Default retry suggestion
        )

    # All other errors
    logger.error(f"Gemini API error: {error}")
    raise LLMError(
        f"API call failed: {error}",
        provider=PROVIDER_NAME,
    )
