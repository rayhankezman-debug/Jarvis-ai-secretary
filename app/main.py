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
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown events.

    This is the modern FastAPI pattern (replaces deprecated @app.on_event).
    Code before `yield` runs on startup, code after runs on shutdown.
    """
    # --- Startup ---
    logger.info("AI Secretary starting up...")
    logger.info(f"Environment: {settings.app_env}")
    logger.info(f"Timezone: {settings.timezone}")
    logger.info(f"Log level: {settings.log_level}")

    yield

    # --- Shutdown ---
    logger.info("AI Secretary shutting down...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    # Initialize logging first
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
