"""
FastAPI application factory.

Why a factory function (create_app)?
- Easier to test (create fresh app instances for each test)
- Configure differently for testing vs production
- Avoid circular imports
- Standard pattern in FastAPI/Flask projects
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level reference to the bot application.
# This is set during lifespan startup and used by the webhook endpoint.
_bot_application = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown events.

    This is the modern FastAPI pattern (replaces deprecated @app.on_event).
    Code before `yield` runs on startup, code after runs on shutdown.

    Phase 1: Initializes and starts the Telegram bot (polling mode).
    """
    global _bot_application

    # --- Startup ---
    logger.info("AI Secretary starting up...")
    logger.info(f"Environment: {settings.app_env}")
    logger.info(f"Timezone: {settings.timezone}")
    logger.info(f"Log level: {settings.log_level}")

    # Start Telegram bot if token is configured
    if settings.telegram_bot_token:
        try:
            from app.telegram.bot import create_bot_application

            _bot_application = create_bot_application()

            # Initialize the bot (connects to Telegram API)
            await _bot_application.initialize()

            # Start polling in the background
            # drop_pending_updates=True avoids processing old messages on restart
            await _bot_application.start()
            await _bot_application.updater.start_polling(
                drop_pending_updates=True,
            )

            logger.info("Telegram bot started (polling mode)")
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}")
            _bot_application = None
    else:
        logger.warning(
            "TELEGRAM_BOT_TOKEN not set — bot disabled. "
            "Set it in .env to enable the Telegram bot."
        )

    yield

    # --- Shutdown ---
    if _bot_application is not None:
        logger.info("Stopping Telegram bot...")
        try:
            if _bot_application.updater and _bot_application.updater.running:
                await _bot_application.updater.stop()
            await _bot_application.stop()
            await _bot_application.shutdown()
            logger.info("Telegram bot stopped gracefully")
        except Exception as e:
            logger.error(f"Error stopping Telegram bot: {e}")

    logger.info("AI Secretary shutting down...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    # Initialize logging first
    from app.core.logging import setup_logging
    setup_logging()

    app = FastAPI(
        title="AI Secretary",
        description="Personal AI assistant for task management, scheduling, and reminders.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register routers
    app.include_router(health_router)

    logger.info("FastAPI application created successfully")
    return app
