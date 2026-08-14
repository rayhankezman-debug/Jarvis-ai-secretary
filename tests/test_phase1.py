"""
Tests for Phase 1 — Telegram Bot Integration.

These tests verify:
1. Bot application creates correctly with a token
2. Bot application raises error without a token
3. Command handlers are registered properly
4. Handler functions respond correctly
5. Error handler works
6. Phase 0 tests still pass (no regressions)

Note: These tests use mocked Telegram objects — no real bot token
or Telegram API calls are needed.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from telegram import Update, User, Chat, Message
from telegram.ext import Application

from app.telegram.handlers import (
    start_command,
    help_command,
    ping_command,
    handle_text_message,
    error_handler,
)


# ──────────────────────────────────────────────
# Fixtures for Telegram mocks
# ──────────────────────────────────────────────

@pytest.fixture
def mock_user():
    """Create a mock Telegram user."""
    user = MagicMock(spec=User)
    user.id = 12345
    user.first_name = "TestUser"
    user.username = "testuser"
    user.is_bot = False
    return user


@pytest.fixture
def mock_chat():
    """Create a mock Telegram chat."""
    chat = MagicMock(spec=Chat)
    chat.id = 12345
    chat.type = "private"
    return chat


@pytest.fixture
def mock_message(mock_user, mock_chat):
    """Create a mock Telegram message with reply_text capability."""
    message = MagicMock(spec=Message)
    message.from_user = mock_user
    message.chat = mock_chat
    message.text = "Hello, bot!"
    message.reply_text = AsyncMock()
    return message


@pytest.fixture
def mock_update(mock_user, mock_message):
    """Create a mock Telegram Update object."""
    update = MagicMock(spec=Update)
    update.effective_user = mock_user
    update.effective_message = mock_message
    update.message = mock_message
    update.update_id = 1
    return update


@pytest.fixture
def mock_context():
    """Create a mock CallbackContext."""
    context = MagicMock()
    context.bot = MagicMock()
    context.error = None
    return context


# ──────────────────────────────────────────────
# Bot Application Creation Tests
# ──────────────────────────────────────────────

def test_bot_creation_fails_without_token():
    """Bot should raise ValueError when TELEGRAM_BOT_TOKEN is empty."""
    with patch("app.telegram.bot.settings") as mock_settings:
        mock_settings.telegram_bot_token = ""

        from app.telegram.bot import create_bot_application
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            create_bot_application()


def test_bot_creation_succeeds_with_token():
    """Bot should create successfully when token is provided."""
    with patch("app.telegram.bot.settings") as mock_settings:
        mock_settings.telegram_bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

        from app.telegram.bot import create_bot_application
        app = create_bot_application()

        assert isinstance(app, Application)


def test_bot_has_command_handlers():
    """Bot should have /start, /help, and /ping handlers registered."""
    with patch("app.telegram.bot.settings") as mock_settings:
        mock_settings.telegram_bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

        from app.telegram.bot import create_bot_application
        app = create_bot_application()

        # Collect all handler commands from registered handlers
        commands = []
        for group_handlers in app.handlers.values():
            for handler in group_handlers:
                if hasattr(handler, "commands"):
                    commands.extend(handler.commands)

        assert "start" in commands
        assert "help" in commands
        assert "ping" in commands


def test_bot_has_message_handler():
    """Bot should have a text message handler registered."""
    with patch("app.telegram.bot.settings") as mock_settings:
        mock_settings.telegram_bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

        from app.telegram.bot import create_bot_application
        app = create_bot_application()

        # Check there's at least one non-command handler
        has_message_handler = False
        for group_handlers in app.handlers.values():
            for handler in group_handlers:
                if not hasattr(handler, "commands"):
                    has_message_handler = True
                    break

        assert has_message_handler, "Bot should have a text message handler"


def test_bot_has_error_handler():
    """Bot should have a global error handler registered."""
    with patch("app.telegram.bot.settings") as mock_settings:
        mock_settings.telegram_bot_token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

        from app.telegram.bot import create_bot_application
        app = create_bot_application()

        assert len(app.error_handlers) > 0, "Bot should have an error handler"


# ──────────────────────────────────────────────
# Handler Function Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_command_sends_welcome(mock_update, mock_context):
    """The /start command should send a welcome message with the user's name."""
    await start_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    response_text = call_args[0][0]

    # Should contain the user's name
    assert "TestUser" in response_text
    # Should mention AI Secretary
    assert "AI Secretary" in response_text
    # Should use HTML parse mode
    assert call_args[1]["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_help_command_lists_commands(mock_update, mock_context):
    """The /help command should list available commands."""
    await help_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    response_text = call_args[0][0]

    # Should list the basic commands
    assert "/start" in response_text
    assert "/help" in response_text
    assert "/ping" in response_text


@pytest.mark.asyncio
async def test_ping_command_returns_pong(mock_update, mock_context):
    """The /ping command should respond with 'Pong' and server time."""
    await ping_command(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    response_text = mock_update.message.reply_text.call_args[0][0]

    assert "Pong" in response_text
    assert "Asia/Jakarta" in response_text


@pytest.mark.asyncio
@patch("app.ai.get_llm_provider", return_value=None)
async def test_text_message_is_acknowledged(mock_provider, mock_update, mock_context):
    """Regular text messages should be acknowledged."""
    mock_update.message.text = "Besok jam 8 kuliah"

    await handle_text_message(mock_update, mock_context)

    mock_update.message.reply_text.assert_called_once()
    call_args = mock_update.message.reply_text.call_args
    response_text = call_args[0][0]

    # Should echo back the message
    assert "Besok jam 8 kuliah" in response_text
    # Should indicate AI is not yet active
    assert "AI belum aktif" in response_text


@pytest.mark.asyncio
@patch("app.ai.get_llm_provider", return_value=None)
async def test_text_message_truncates_long_input(mock_provider, mock_update, mock_context):
    """Long messages should be truncated in the echo response."""
    mock_update.message.text = "A" * 500

    await handle_text_message(mock_update, mock_context)

    response_text = mock_update.message.reply_text.call_args[0][0]
    # The handler truncates at 200 chars
    assert "A" * 200 in response_text
    assert "A" * 201 not in response_text


@pytest.mark.asyncio
@patch("app.ai.get_llm_provider", return_value=None)
async def test_text_message_escapes_html(mock_provider, mock_update, mock_context):
    """HTML in user messages should be escaped to prevent injection."""
    mock_update.message.text = "<script>alert('xss')</script>"

    await handle_text_message(mock_update, mock_context)

    response_text = mock_update.message.reply_text.call_args[0][0]
    # Raw HTML tags should be escaped
    assert "<script>" not in response_text
    assert "&lt;script&gt;" in response_text


# ──────────────────────────────────────────────
# Error Handler Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_handler_sends_message(mock_update, mock_context):
    """Error handler should send an error message to the user."""
    mock_context.error = ValueError("Test error")

    await error_handler(mock_update, mock_context)

    mock_update.effective_message.reply_text.assert_called_once()
    response_text = mock_update.effective_message.reply_text.call_args[0][0]
    assert "kesalahan" in response_text.lower() or "error" in response_text.lower()


@pytest.mark.asyncio
async def test_error_handler_survives_reply_failure(mock_context):
    """Error handler should not crash if it can't send a message."""
    mock_context.error = ValueError("Test error")

    # update with a message that fails to reply
    update = MagicMock(spec=Update)
    update.effective_message = MagicMock()
    update.effective_message.reply_text = AsyncMock(side_effect=Exception("Network error"))

    # Should not raise — errors in the error handler itself are caught
    await error_handler(update, mock_context)


@pytest.mark.asyncio
async def test_error_handler_handles_no_update(mock_context):
    """Error handler should work even when update is None."""
    mock_context.error = ValueError("Test error")

    # Should not raise
    await error_handler(None, mock_context)


# ──────────────────────────────────────────────
# FastAPI Integration Tests (bot disabled)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_still_works(client):
    """Health endpoint should still work with bot disabled (no token)."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
