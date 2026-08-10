"""
Entry point for running the application.

Usage:
    python run.py

This starts the uvicorn server with the FastAPI app.
In production, you'd typically run uvicorn directly:
    uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
"""

import uvicorn

from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=8000,
        reload=(settings.app_env == "development"),
    )
