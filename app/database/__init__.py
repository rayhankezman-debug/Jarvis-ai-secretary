"""
Database package — SQLAlchemy models and async session management.

Public API:
    Base              — Declarative base for all models
    TimestampMixin    — Adds created_at/updated_at columns
    Task              — Core task model
    TaskStatus        — Task lifecycle enum
    TaskPriority      — Task priority enum
    get_db_session    — Async context manager for DB sessions
    check_db_connection — Health check helper
"""

from app.database.base import Base, TimestampMixin
from app.database.models import Task, TaskStatus, TaskPriority
from app.database.session import get_db_session, check_db_connection

__all__ = [
    "Base",
    "TimestampMixin",
    "Task",
    "TaskStatus",
    "TaskPriority",
    "get_db_session",
    "check_db_connection",
]
