"""
Async database engine and session management.

This module provides:
- create_async_engine: Configured SQLAlchemy async engine
- AsyncSessionLocal: Session factory for creating database sessions
- get_db_session: Async context manager for safe session usage

Why async?
- FastAPI is async-first, so DB calls should be non-blocking
- asyncpg is significantly faster than psycopg2 for PostgreSQL
- Consistent async/await pattern throughout the application

Connection pooling:
- pool_size=5: Keep 5 connections warm (good for single-server MVP)
- max_overflow=10: Allow up to 15 total connections under load
- pool_pre_ping=True: Verify connections are alive before using them
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine as _create_async_engine,
)

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# --- Engine ---
# The engine is the starting point for all SQLAlchemy database operations.
# It manages the connection pool and dialect (PostgreSQL via asyncpg).
engine = _create_async_engine(
    settings.database_url,
    echo=(settings.app_env == "development"),  # Log SQL in dev mode
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

# --- Session Factory ---
# async_sessionmaker creates AsyncSession instances.
# expire_on_commit=False prevents lazy-loading issues after commit
# (accessing attributes after commit won't trigger a new DB query).
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager that provides a database session.

    Usage:
        async with get_db_session() as session:
            result = await session.execute(select(Task))

    The session is automatically:
    - Committed on success
    - Rolled back on exception
    - Closed when done

    This pattern ensures no leaked connections or uncommitted transactions.
    """
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_db_connection() -> bool:
    """
    Test if the database is reachable.

    Used by the health check endpoint to report DB status.
    Returns True if a simple query succeeds, False otherwise.
    """
    try:
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database connection check failed: {e}")
        return False


async def dispose_engine() -> None:
    """
    Dispose the engine and close all pooled connections.

    Called during application shutdown to cleanly release resources.
    """
    await engine.dispose()
    logger.info("Database engine disposed")
