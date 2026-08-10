"""
SQLAlchemy declarative base and shared model utilities.

All database models inherit from Base defined here.
This ensures a single metadata registry for all models,
which is required for Alembic migrations to discover tables.

Why a separate base.py?
- Avoids circular imports (models.py imports Base, session.py imports Base)
- Single source of truth for the declarative base
- Common columns (id, created_at, updated_at) defined once
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.

    All models automatically get:
    - id: Auto-incrementing primary key
    - created_at: Timestamp set on creation (server-side)
    - updated_at: Timestamp updated on every modification (server-side)
    """
    pass


class TimestampMixin:
    """
    Mixin that adds created_at and updated_at columns.

    Uses server_default for created_at so the database handles timestamps,
    making them consistent regardless of application server time.

    Why a mixin instead of putting these in Base?
    - More explicit — you opt-in to timestamps per model
    - Some tables (like association tables) don't need timestamps
    - Easier to test in isolation
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
