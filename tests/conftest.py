"""
Pytest configuration and shared fixtures.

Fixtures defined here are automatically available to ALL test files
without needing to import them.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    """Create a fresh FastAPI app instance for testing."""
    return create_app()


@pytest.fixture
async def client(app):
    """
    Async HTTP client for testing API endpoints.

    Uses httpx.AsyncClient which sends requests directly to the app
    in-memory (no real HTTP server needed). This is fast and isolated.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
