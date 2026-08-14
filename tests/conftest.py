"""
Pytest configuration and shared fixtures.

Fixtures defined here are automatically available to ALL test files
without needing to import them.
"""

import pytest
from unittest.mock import patch
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture(autouse=True)
def _reset_ai_singletons():
    """
    Reset AI singletons and disable the agent by default.

    Phase 1/3 handler tests were written before the agent existed.
    They expect the handler to use get_llm_provider, not the agent.
    By default, get_agent returns None so those tests still pass.

    Phase 4 tests that need the agent provide their own patches.
    """
    from app.ai import reset_provider
    from app.ai.agent import reset_agent
    reset_provider()
    reset_agent()

    # Disable agent by default so pre-Phase 4 handler tests that only mock
    # get_llm_provider still work. Phase 4 tests provide their own agent patches.
    with patch("app.ai.agent.get_agent", return_value=None):
        yield

    reset_provider()
    reset_agent()


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
