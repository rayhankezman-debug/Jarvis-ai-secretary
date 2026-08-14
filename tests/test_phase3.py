"""
Tests for Phase 3 — Gemini AI Integration.

These tests verify:
1. GeminiProvider implements LLMProvider interface
2. Provider requires API key
3. System prompt is generated correctly
4. generate_text works with mocked Gemini client
5. generate_structured_response works with mocked Gemini client
6. Error handling maps to our LLM error hierarchy
7. Rate limit detection works
8. AI package factory function works
9. Telegram handler routes to AI when available
10. Telegram handler falls back when AI is unavailable
11. Phase 0/1/2 regressions are caught

Note: All Gemini API calls are mocked — no real API key needed for testing.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.base import (
    LLMError,
    LLMInvalidResponseError,
    LLMProvider,
    LLMRateLimitError,
)
from app.ai.gemini import GeminiProvider, _handle_gemini_error
from app.ai.prompts import get_system_prompt, CONVERSATIONAL_PROMPT


# ──────────────────────────────────────────────
# System Prompt Tests
# ──────────────────────────────────────────────

def test_system_prompt_contains_timezone():
    """System prompt should include the configured timezone."""
    prompt = get_system_prompt()
    assert "Asia/Jakarta" in prompt


def test_system_prompt_defines_role():
    """System prompt should define the AI Secretary role."""
    prompt = get_system_prompt()
    assert "AI Secretary" in prompt


def test_system_prompt_mentions_language_rules():
    """System prompt should instruct about language matching."""
    prompt = get_system_prompt()
    assert "Bahasa Indonesia" in prompt


def test_system_prompt_mentions_upcoming_features():
    """System prompt should mention features that are coming soon."""
    prompt = get_system_prompt()
    assert "Phase 4" in prompt or "akan datang" in prompt.lower()


def test_conversational_prompt_exists():
    """CONVERSATIONAL_PROMPT should be a non-empty string."""
    assert isinstance(CONVERSATIONAL_PROMPT, str)
    assert len(CONVERSATIONAL_PROMPT) > 0


# ──────────────────────────────────────────────
# GeminiProvider Initialization Tests
# ──────────────────────────────────────────────

def test_gemini_provider_requires_api_key():
    """GeminiProvider should raise ValueError without an API key."""
    with patch("app.ai.gemini.settings") as mock_settings:
        mock_settings.gemini_api_key = ""
        mock_settings.gemini_model = "gemini-2.0-flash"

        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            GeminiProvider()


def test_gemini_provider_accepts_explicit_key():
    """GeminiProvider should accept an explicit API key."""
    provider = GeminiProvider(api_key="test-key-123", model="gemini-2.0-flash")
    assert isinstance(provider, LLMProvider)


def test_gemini_provider_implements_interface():
    """GeminiProvider should be a proper LLMProvider subclass."""
    provider = GeminiProvider(api_key="test-key-123", model="gemini-2.0-flash")
    assert isinstance(provider, LLMProvider)
    assert hasattr(provider, "generate_text")
    assert hasattr(provider, "generate_structured_response")


# ──────────────────────────────────────────────
# generate_text Tests (mocked API)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_text_returns_string():
    """generate_text should return the model's text response."""
    provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")

    # Mock the async client response
    mock_response = MagicMock()
    mock_response.text = "Halo! Saya AI Secretary. Ada yang bisa saya bantu?"

    provider._client = MagicMock()
    provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    result = await provider.generate_text("Halo!")
    assert result == "Halo! Saya AI Secretary. Ada yang bisa saya bantu?"


@pytest.mark.asyncio
async def test_generate_text_raises_on_empty_response():
    """generate_text should raise LLMError on empty response."""
    provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")

    mock_response = MagicMock()
    mock_response.text = ""

    provider._client = MagicMock()
    provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with pytest.raises(LLMError, match="Empty"):
        await provider.generate_text("Hello")


@pytest.mark.asyncio
async def test_generate_text_raises_on_none_response():
    """generate_text should raise LLMError on None text."""
    provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")

    mock_response = MagicMock()
    mock_response.text = None

    provider._client = MagicMock()
    provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with pytest.raises(LLMError):
        await provider.generate_text("Hello")


# ──────────────────────────────────────────────
# generate_structured_response Tests (mocked API)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_structured_response_returns_dict():
    """generate_structured_response should parse JSON and return a dict."""
    provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")

    mock_response = MagicMock()
    mock_response.text = json.dumps({
        "intent": "create_task",
        "title": "Beli susu",
        "priority": "medium",
    })

    provider._client = MagicMock()
    provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    result = await provider.generate_structured_response("Beli susu besok")
    assert isinstance(result, dict)
    assert result["intent"] == "create_task"
    assert result["title"] == "Beli susu"


@pytest.mark.asyncio
async def test_structured_response_raises_on_invalid_json():
    """generate_structured_response should raise on non-JSON response."""
    provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")

    mock_response = MagicMock()
    mock_response.text = "This is not valid JSON {{"

    provider._client = MagicMock()
    provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with pytest.raises(LLMInvalidResponseError, match="parse JSON"):
        await provider.generate_structured_response("test")


@pytest.mark.asyncio
async def test_structured_response_raises_on_empty():
    """generate_structured_response should raise on empty response."""
    provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")

    mock_response = MagicMock()
    mock_response.text = ""

    provider._client = MagicMock()
    provider._client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with pytest.raises(LLMInvalidResponseError, match="Empty"):
        await provider.generate_structured_response("test")


# ──────────────────────────────────────────────
# Error Handling Tests
# ──────────────────────────────────────────────

def test_handle_rate_limit_429():
    """429 errors should map to LLMRateLimitError."""
    with pytest.raises(LLMRateLimitError) as exc_info:
        _handle_gemini_error(Exception("429 Resource Exhausted"))

    assert exc_info.value.provider == "gemini"
    assert exc_info.value.retry_after == 60.0


def test_handle_rate_limit_resource_exhausted():
    """'resource exhausted' errors should map to LLMRateLimitError."""
    with pytest.raises(LLMRateLimitError):
        _handle_gemini_error(Exception("RESOURCE_EXHAUSTED: quota exceeded"))


def test_handle_generic_api_error():
    """Non-rate-limit errors should map to LLMError."""
    with pytest.raises(LLMError) as exc_info:
        _handle_gemini_error(Exception("Internal server error"))

    assert exc_info.value.provider == "gemini"
    assert not isinstance(exc_info.value, LLMRateLimitError)


@pytest.mark.asyncio
async def test_generate_text_maps_api_errors():
    """API exceptions during generate_text should be converted to LLMError."""
    provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")

    provider._client = MagicMock()
    provider._client.aio.models.generate_content = AsyncMock(
        side_effect=Exception("Connection failed")
    )

    with pytest.raises(LLMError, match="Connection failed"):
        await provider.generate_text("Hello")


@pytest.mark.asyncio
async def test_generate_text_detects_rate_limit():
    """Rate limit during generate_text should raise LLMRateLimitError."""
    provider = GeminiProvider(api_key="test-key", model="gemini-2.0-flash")

    provider._client = MagicMock()
    provider._client.aio.models.generate_content = AsyncMock(
        side_effect=Exception("429 Too Many Requests")
    )

    with pytest.raises(LLMRateLimitError):
        await provider.generate_text("Hello")


# ──────────────────────────────────────────────
# AI Package Factory Tests
# ──────────────────────────────────────────────

def test_get_llm_provider_returns_none_without_key():
    """get_llm_provider should return None when API key is missing."""
    from app.ai import reset_provider
    reset_provider()

    with patch("app.ai.settings") as mock_settings:
        mock_settings.gemini_api_key = ""
        from app.ai import get_llm_provider
        provider = get_llm_provider()
        assert provider is None

    reset_provider()


def test_get_llm_provider_returns_provider_with_key():
    """get_llm_provider should return a GeminiProvider when key is set."""
    from app.ai import reset_provider
    reset_provider()

    with patch("app.ai.settings") as mock_settings:
        mock_settings.gemini_api_key = "test-key-123"
        mock_settings.gemini_model = "gemini-2.0-flash"
        from app.ai import get_llm_provider
        provider = get_llm_provider()
        assert isinstance(provider, GeminiProvider)

    reset_provider()


def test_reset_provider_clears_cache():
    """reset_provider should clear the cached instance."""
    from app.ai import reset_provider, _provider_instance
    reset_provider()
    # After reset, module variable should be None
    import app.ai
    assert app.ai._provider_instance is None


# ──────────────────────────────────────────────
# Telegram Handler Integration Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_text_handler_uses_ai_when_available():
    """Text handler should use AI provider when available."""
    from app.telegram.handlers import handle_text_message

    # Create mock update/context
    mock_update = MagicMock()
    mock_update.effective_user = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.message = MagicMock()
    mock_update.message.text = "Halo apa kabar?"
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()

    # Mock the AI provider to return a response
    mock_provider = MagicMock()
    mock_provider.generate_text = AsyncMock(return_value="Halo! Saya baik, ada yang bisa dibantu?")

    with patch("app.ai.get_llm_provider", return_value=mock_provider):
        await handle_text_message(mock_update, mock_context)

    # Should have called reply_text with the AI response
    mock_update.message.reply_text.assert_called_once_with(
        "Halo! Saya baik, ada yang bisa dibantu?"
    )


@pytest.mark.asyncio
async def test_text_handler_fallback_when_ai_unavailable():
    """Text handler should fall back to echo when AI is not available."""
    from app.telegram.handlers import handle_text_message

    mock_update = MagicMock()
    mock_update.effective_user = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.message = MagicMock()
    mock_update.message.text = "Halo apa kabar?"
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()

    # Mock AI as unavailable
    with patch("app.ai.get_llm_provider", return_value=None):
        await handle_text_message(mock_update, mock_context)

    # Should fall back to echo response
    call_args = mock_update.message.reply_text.call_args
    response_text = call_args[0][0]
    assert "AI belum aktif" in response_text


@pytest.mark.asyncio
async def test_text_handler_fallback_when_ai_fails():
    """Text handler should fall back to echo when AI raises an error."""
    from app.telegram.handlers import handle_text_message

    mock_update = MagicMock()
    mock_update.effective_user = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.message = MagicMock()
    mock_update.message.text = "Test message"
    mock_update.message.reply_text = AsyncMock()

    mock_context = MagicMock()

    # Mock AI that throws an error
    mock_provider = MagicMock()
    mock_provider.generate_text = AsyncMock(side_effect=LLMError("API failed", provider="gemini"))

    with patch("app.ai.get_llm_provider", return_value=mock_provider):
        await handle_text_message(mock_update, mock_context)

    # Should fall back to echo response (not crash)
    call_args = mock_update.message.reply_text.call_args
    response_text = call_args[0][0]
    assert "AI belum aktif" in response_text or "Pesan diterima" in response_text


# ──────────────────────────────────────────────
# Regression Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint_still_works(client):
    """Health endpoint should still return 200 after Phase 3 changes."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"


def test_phase0_llm_interface_unchanged():
    """LLMProvider abstract interface should still be intact."""
    with pytest.raises(TypeError):
        LLMProvider()


def test_phase0_llm_error_hierarchy():
    """LLM error hierarchy should still work."""
    error = LLMRateLimitError("rate limited", provider="gemini", retry_after=30.0)
    assert isinstance(error, LLMError)
    assert error.retry_after == 30.0
