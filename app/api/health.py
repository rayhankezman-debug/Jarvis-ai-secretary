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

    health = {
        "status": "healthy",
        "environment": settings.app_env,
        "timezone": settings.timezone,
        "current_time": now.isoformat(),
        "version": "0.1.0",
    }

    # Check database connectivity (non-blocking, doesn't fail the endpoint)
    try:
        from app.database.session import check_db_connection
        health["database"] = "connected" if await check_db_connection() else "disconnected"
    except Exception:
        health["database"] = "unavailable"

    return health
