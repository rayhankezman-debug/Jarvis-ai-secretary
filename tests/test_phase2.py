"""
Tests for Phase 2 — Database (PostgreSQL + SQLAlchemy).

These tests verify:
1. Models can be imported and have correct structure
2. Task model creates with proper defaults
3. Task enums have expected values
4. TimestampMixin provides created_at/updated_at
5. Session factory creates and manages sessions
6. CRUD operations work (create, read, update, delete)
7. Health endpoint still works (no regressions)

Note: Tests use SQLite in-memory database via aiosqlite.
No PostgreSQL installation needed for testing.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database.base import Base, TimestampMixin
from app.database.models import Task, TaskStatus, TaskPriority


# ──────────────────────────────────────────────
# Test Database Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
async def test_engine():
    """Create an in-memory SQLite async engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",  # In-memory SQLite
        echo=False,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def test_session(test_engine):
    """Create an async session bound to the test engine."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session


# ──────────────────────────────────────────────
# Model Import & Structure Tests
# ──────────────────────────────────────────────

def test_task_model_exists():
    """Task model should be importable."""
    assert Task is not None


def test_task_tablename():
    """Task model should map to 'tasks' table."""
    assert Task.__tablename__ == "tasks"


def test_task_has_required_columns():
    """Task model should have all expected columns."""
    column_names = {c.name for c in Task.__table__.columns}
    expected = {
        "id", "telegram_user_id", "title", "description",
        "status", "priority", "due_date", "completed_at",
        "created_at", "updated_at",
    }
    assert expected.issubset(column_names), (
        f"Missing columns: {expected - column_names}"
    )


def test_task_id_is_primary_key():
    """Task.id should be the primary key."""
    pk_columns = [c.name for c in Task.__table__.primary_key.columns]
    assert "id" in pk_columns


def test_telegram_user_id_is_indexed():
    """telegram_user_id should be indexed for fast lookups."""
    col = Task.__table__.columns["telegram_user_id"]
    assert col.index is True


def test_status_is_indexed():
    """status should be indexed for filtering queries."""
    col = Task.__table__.columns["status"]
    assert col.index is True


# ──────────────────────────────────────────────
# Enum Tests
# ──────────────────────────────────────────────

def test_task_status_values():
    """TaskStatus enum should have the expected lifecycle states."""
    assert TaskStatus.PENDING == "pending"
    assert TaskStatus.IN_PROGRESS == "in_progress"
    assert TaskStatus.COMPLETED == "completed"
    assert TaskStatus.CANCELLED == "cancelled"


def test_task_priority_values():
    """TaskPriority enum should have the expected priority levels."""
    assert TaskPriority.LOW == "low"
    assert TaskPriority.MEDIUM == "medium"
    assert TaskPriority.HIGH == "high"
    assert TaskPriority.URGENT == "urgent"


def test_task_status_is_str_enum():
    """TaskStatus should be a string enum for JSON serialization."""
    assert isinstance(TaskStatus.PENDING, str)
    assert isinstance(TaskStatus.PENDING, TaskStatus)


def test_task_priority_is_str_enum():
    """TaskPriority should be a string enum for JSON serialization."""
    assert isinstance(TaskPriority.MEDIUM, str)
    assert isinstance(TaskPriority.MEDIUM, TaskPriority)


# ──────────────────────────────────────────────
# CRUD Operation Tests (using SQLite in-memory)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_task(test_session):
    """Should create a task with required fields."""
    task = Task(
        telegram_user_id=12345,
        title="Buy groceries",
        status=TaskStatus.PENDING,
        priority=TaskPriority.MEDIUM,
    )
    test_session.add(task)
    await test_session.commit()

    assert task.id is not None
    assert task.title == "Buy groceries"
    assert task.telegram_user_id == 12345


@pytest.mark.asyncio
async def test_task_default_status(test_session):
    """Task should default to PENDING status."""
    task = Task(
        telegram_user_id=12345,
        title="Test task",
    )
    test_session.add(task)
    await test_session.commit()

    assert task.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_task_default_priority(test_session):
    """Task should default to MEDIUM priority."""
    task = Task(
        telegram_user_id=12345,
        title="Test task",
    )
    test_session.add(task)
    await test_session.commit()

    assert task.priority == TaskPriority.MEDIUM


@pytest.mark.asyncio
async def test_read_task(test_session):
    """Should be able to query tasks from the database."""
    task = Task(
        telegram_user_id=99999,
        title="Read me",
        priority=TaskPriority.HIGH,
    )
    test_session.add(task)
    await test_session.commit()

    # Query it back
    result = await test_session.execute(
        select(Task).where(Task.telegram_user_id == 99999)
    )
    fetched = result.scalar_one()

    assert fetched.title == "Read me"
    assert fetched.priority == TaskPriority.HIGH


@pytest.mark.asyncio
async def test_update_task(test_session):
    """Should update task fields and persist changes."""
    task = Task(
        telegram_user_id=12345,
        title="Old title",
    )
    test_session.add(task)
    await test_session.commit()

    # Update
    task.title = "New title"
    task.status = TaskStatus.IN_PROGRESS
    await test_session.commit()

    # Verify
    result = await test_session.execute(
        select(Task).where(Task.id == task.id)
    )
    updated = result.scalar_one()
    assert updated.title == "New title"
    assert updated.status == TaskStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_delete_task(test_session):
    """Should delete a task from the database."""
    task = Task(
        telegram_user_id=12345,
        title="Delete me",
    )
    test_session.add(task)
    await test_session.commit()
    task_id = task.id

    # Delete
    await test_session.delete(task)
    await test_session.commit()

    # Verify it's gone
    result = await test_session.execute(
        select(Task).where(Task.id == task_id)
    )
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_task_with_description(test_session):
    """Task should support optional description."""
    task = Task(
        telegram_user_id=12345,
        title="Task with notes",
        description="This is a detailed description of the task.",
    )
    test_session.add(task)
    await test_session.commit()

    result = await test_session.execute(
        select(Task).where(Task.id == task.id)
    )
    fetched = result.scalar_one()
    assert fetched.description == "This is a detailed description of the task."


@pytest.mark.asyncio
async def test_task_with_due_date(test_session):
    """Task should support optional due date."""
    due = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    task = Task(
        telegram_user_id=12345,
        title="New Year task",
        due_date=due,
    )
    test_session.add(task)
    await test_session.commit()

    result = await test_session.execute(
        select(Task).where(Task.id == task.id)
    )
    fetched = result.scalar_one()
    assert fetched.due_date is not None


@pytest.mark.asyncio
async def test_task_without_optional_fields(test_session):
    """Task should work with only required fields (description & due_date are optional)."""
    task = Task(
        telegram_user_id=12345,
        title="Minimal task",
    )
    test_session.add(task)
    await test_session.commit()

    assert task.description is None
    assert task.due_date is None
    assert task.completed_at is None


@pytest.mark.asyncio
async def test_multiple_tasks_per_user(test_session):
    """A user should be able to have multiple tasks."""
    user_id = 12345
    for i in range(5):
        test_session.add(Task(
            telegram_user_id=user_id,
            title=f"Task {i}",
        ))
    await test_session.commit()

    result = await test_session.execute(
        select(Task).where(Task.telegram_user_id == user_id)
    )
    tasks = result.scalars().all()
    assert len(tasks) == 5


@pytest.mark.asyncio
async def test_filter_tasks_by_status(test_session):
    """Should be able to filter tasks by status."""
    user_id = 12345
    test_session.add(Task(telegram_user_id=user_id, title="Pending 1"))
    test_session.add(Task(telegram_user_id=user_id, title="Pending 2"))
    test_session.add(Task(
        telegram_user_id=user_id,
        title="Done",
        status=TaskStatus.COMPLETED,
    ))
    await test_session.commit()

    # Query only pending
    result = await test_session.execute(
        select(Task).where(
            Task.telegram_user_id == user_id,
            Task.status == TaskStatus.PENDING,
        )
    )
    pending = result.scalars().all()
    assert len(pending) == 2


# ──────────────────────────────────────────────
# Model Method Tests
# ──────────────────────────────────────────────

def test_task_repr():
    """Task repr should show id, truncated title, status, and priority."""
    task = Task(
        id=1,
        telegram_user_id=12345,
        title="A very long task title that should be truncated in repr",
        status=TaskStatus.PENDING,
        priority=TaskPriority.HIGH,
    )
    repr_str = repr(task)
    assert "Task" in repr_str
    assert "pending" in repr_str
    assert "high" in repr_str


def test_mark_completed():
    """mark_completed() should set status and completed_at."""
    task = Task(
        telegram_user_id=12345,
        title="Complete me",
        status=TaskStatus.PENDING,
        priority=TaskPriority.MEDIUM,
    )
    task.mark_completed()

    assert task.status == TaskStatus.COMPLETED
    assert task.completed_at is not None
    assert isinstance(task.completed_at, datetime)


def test_mark_cancelled():
    """mark_cancelled() should set status to CANCELLED."""
    task = Task(
        telegram_user_id=12345,
        title="Cancel me",
        status=TaskStatus.PENDING,
        priority=TaskPriority.MEDIUM,
    )
    task.mark_cancelled()

    assert task.status == TaskStatus.CANCELLED


# ──────────────────────────────────────────────
# Base & Mixin Tests
# ──────────────────────────────────────────────

def test_base_is_declarative():
    """Base should be a proper SQLAlchemy DeclarativeBase."""
    from sqlalchemy.orm import DeclarativeBase
    assert issubclass(Base, DeclarativeBase)


def test_timestamp_mixin_has_fields():
    """TimestampMixin should provide created_at and updated_at."""
    assert hasattr(TimestampMixin, "created_at")
    assert hasattr(TimestampMixin, "updated_at")


def test_task_inherits_timestamp_mixin():
    """Task model should have created_at and updated_at from TimestampMixin."""
    columns = {c.name for c in Task.__table__.columns}
    assert "created_at" in columns
    assert "updated_at" in columns


# ──────────────────────────────────────────────
# Database Package Import Tests
# ──────────────────────────────────────────────

def test_database_package_exports():
    """Database package should export all public symbols."""
    from app.database import (
        Base,
        TimestampMixin,
        Task,
        TaskStatus,
        TaskPriority,
        get_db_session,
        check_db_connection,
    )
    assert Base is not None
    assert Task is not None
    assert get_db_session is not None


# ──────────────────────────────────────────────
# Regression Tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint_still_works(client):
    """Health endpoint should still return 200 after Phase 2 changes."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"
    # Database field should now exist (may be unavailable without real DB)
    assert "database" in data
