"""
Telegram Bot Application setup.

This module creates and configures the python-telegram-bot Application.
It is responsible for:
- Building the bot Application with the token from settings
- Registering all command and message handlers
- Providing lifecycle management (initialize, start, shutdown)

Architecture:
    bot.py (this file) — Application factory + handler registration
    handlers.py        — Individual handler functions (command logic)

Why separate bot.py from handlers.py?
- bot.py handles "wiring" (what handlers exist and how they connect)
- handlers.py handles "logic" (what each command actually does)
- Easier to test handlers in isolation
- Clear separation of concerns
"""

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.core.config import settings
from app.core.logging import get_logger
from app.telegram.handlers import (
    start_command,
    help_command,
    ping_command,
    handle_text_message,
    error_handler,
)

logger = get_logger(__name__)


def create_bot_application() -> Application:
    """
    Build and configure the Telegram bot Application.

    This sets up:
    1. The Application with the bot token
    2. Command handlers (/start, /help, /ping)
    3. A catch-all text message handler
    4. A global error handler

    Returns:
        Configured Application ready to be initialized and started.
    """
    if not settings.telegram_bot_token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Please set it in your .env file. "
            "Get a token from @BotFather on Telegram."
        )

    # Build the Application
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    # --- Register Command Handlers ---
    # Order matters: more specific handlers should come first.
    # Commands are automatically case-insensitive.
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("ping", ping_command))

    # --- Register Message Handlers ---
    # Catch-all for regular text messages (not commands).
    # This is where user natural language input will be processed
    # by the AI in future phases.
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    # --- Global Error Handler ---
    application.add_error_handler(error_handler)

    logger.info("Telegram bot application created with handlers registered")
    return application
