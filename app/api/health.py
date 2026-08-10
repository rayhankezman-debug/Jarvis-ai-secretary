"""
Health check and utility API routes.

These routes are always available, regardless of which features
are enabled. Used for monitoring and debugging.
"""

from datetime import datetime

import pytz
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """
    Application health check.

    Returns basic status info. Useful for:
    - Monitoring tools (uptime checks)
    - Verifying the app is running
    - Quick debugging of config issues
    """
    tz = pytz.timezone(settings.timezone)
    now = datetime.now(tz)

    return {
        "status": "healthy",
        "environment": settings.app_env,
        "timezone": settings.timezone,
        "current_time": now.isoformat(),
        "version": "0.1.0",
    }
