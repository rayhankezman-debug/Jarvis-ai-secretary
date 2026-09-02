"""
Tests for batch task cancellation — Fix for the "bersihkan" bug.

These tests verify:
1. TaskService.batch_cancel_tasks modifies DB state correctly
2. User isolation: user A cannot cancel user B's tasks
3. Missing/nonexistent task IDs are reported, not silently ignored
4. Empty input is handled safely
5. Already-cancelled/completed tasks are skipped
6. DailyPlanService excludes cancelled tasks
7. Tool declaration and executor wiring
8. Anti-hallucination guardrail exists in system prompt

Root cause of the original bug:
- No batch cancel tool existed
- Gemini hallucinated a success response without calling any tool
- Tasks remained PENDING in the database
- DailyPlanService correctly showed the uncancelled tasks
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database.base import Base
from app.database.models import Task, TaskStatus, TaskPriority

pytestmark = pytest.mark.asyncio


# ──────────────────────────────────────────────
# Test Database Fixtures
# ──────────────────────────────────────────────

USER_A = 111111
USER_B = 222222


@pytest.fixture
async def test_engine():
    """Create an in-memory SQLite async engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def test_session_factory(test_engine):
    """Session factory for the test engine."""
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture(autouse=True)
def mock_db_session(test_session_factory):
    """
    Patch get_db_session in all relevant service modules.

    Uses the same session factory pattern as test_memory_service.py.
    Each service call gets a fresh session from the same in-memory engine,
    ensuring proper transaction isolation while sharing state.
    """
    @asynccontextmanager
    async def get_test_session():
        async with test_session_factory() as session:
            yield session
            await session.commit()

    with patch("app.services.task_service.get_db_session", new=get_test_session), \
         patch("app.services.daily_plan_service.get_db_session", new=get_test_session):
        yield


async def _create_task(
    session_factory,
    user_id,
    title,
    status=TaskStatus.PENDING,
    priority=TaskPriority.MEDIUM,
    due_date=None,
):
    """Helper to create a task directly in the test DB."""
    async with session_factory() as session:
        task = Task(
            telegram_user_id=user_id,
            title=title,
            status=status,
            priority=priority,
            due_date=due_date,
        )
        session.add(task)
        await session.commit()
        return task


async def _get_task_status(session_factory, task_id):
    """Helper to verify actual DB status of a task."""
    async with session_factory() as session:
        result = await session.execute(
            select(Task).where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        return task.status if task else None


# ──────────────────────────────────────────────
# Part 1: TaskService.batch_cancel_tasks
# ──────────────────────────────────────────────

class TestBatchCancelModifiesDB:
    """Verify batch_cancel_tasks actually changes database state."""

    async def test_batch_cancel_changes_status(self, test_session_factory):
        """Created pending tasks should become CANCELLED after batch cancel."""
        from app.services.task_service import TaskService

        t1 = await _create_task(test_session_factory, USER_A, "Task 1")
        t2 = await _create_task(test_session_factory, USER_A, "Task 2")
        t3 = await _create_task(test_session_factory, USER_A, "Task 3")

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[t1.id, t2.id, t3.id],
        )

        assert result["success"] is True
        assert result["cancelled_count"] == 3
        assert len(result["cancelled_tasks"]) == 3

        # Verify actual DB state
        for task_id in [t1.id, t2.id, t3.id]:
            status = await _get_task_status(test_session_factory, task_id)
            assert status == TaskStatus.CANCELLED

    async def test_batch_cancel_returns_cancelled_titles(self, test_session_factory):
        """Result should include task IDs and titles of cancelled tasks."""
        from app.services.task_service import TaskService

        t1 = await _create_task(test_session_factory, USER_A, "Seminar AI")
        t2 = await _create_task(test_session_factory, USER_A, "Belajar Python")

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[t1.id, t2.id],
        )

        cancelled_ids = {t["task_id"] for t in result["cancelled_tasks"]}
        cancelled_titles = {t["title"] for t in result["cancelled_tasks"]}
        assert t1.id in cancelled_ids
        assert t2.id in cancelled_ids
        assert "Seminar AI" in cancelled_titles
        assert "Belajar Python" in cancelled_titles

    async def test_batch_cancel_in_progress_tasks(self, test_session_factory):
        """IN_PROGRESS tasks should also be cancellable."""
        from app.services.task_service import TaskService

        t1 = await _create_task(
            test_session_factory, USER_A, "Active task",
            status=TaskStatus.IN_PROGRESS,
        )

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[t1.id],
        )

        assert result["success"] is True
        assert result["cancelled_count"] == 1

        status = await _get_task_status(test_session_factory, t1.id)
        assert status == TaskStatus.CANCELLED


class TestBatchCancelUserIsolation:
    """Verify batch_cancel_tasks enforces telegram_user_id isolation."""

    async def test_cannot_cancel_other_users_tasks(self, test_session_factory):
        """User A cannot cancel User B's tasks via batch cancel."""
        from app.services.task_service import TaskService

        task_a = await _create_task(test_session_factory, USER_A, "A's task")
        task_b = await _create_task(test_session_factory, USER_B, "B's task")

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[task_a.id, task_b.id],
        )

        # Only A's task should be cancelled
        assert result["cancelled_count"] == 1
        assert result["cancelled_tasks"][0]["task_id"] == task_a.id

        # B's task should be in not_found (not visible to user A)
        assert len(result["not_found_tasks"]) == 1
        assert result["not_found_tasks"][0]["task_id"] == task_b.id

        # Verify B's task is still PENDING in DB
        status_b = await _get_task_status(test_session_factory, task_b.id)
        assert status_b == TaskStatus.PENDING

    async def test_all_foreign_ids_returns_no_success(self, test_session_factory):
        """If ALL provided IDs belong to another user, success=False."""
        from app.services.task_service import TaskService

        task_b = await _create_task(test_session_factory, USER_B, "B's only task")

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[task_b.id],
        )

        assert result["success"] is False
        assert result["cancelled_count"] == 0
        assert len(result["not_found_tasks"]) == 1


class TestBatchCancelEdgeCases:
    """Verify edge case handling."""

    async def test_nonexistent_task_id(self, test_session_factory):
        """Nonexistent task IDs are reported in not_found_tasks."""
        from app.services.task_service import TaskService

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[99999],
        )

        assert result["success"] is False
        assert result["cancelled_count"] == 0
        assert len(result["not_found_tasks"]) == 1
        assert result["not_found_tasks"][0]["task_id"] == 99999

    async def test_empty_task_ids(self, test_session_factory):
        """Empty task ID list is handled safely."""
        from app.services.task_service import TaskService

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[],
        )

        assert result["success"] is False
        assert result["cancelled_count"] == 0
        assert "kosong" in result.get("error", "").lower()

    async def test_already_cancelled_tasks_are_skipped(self, test_session_factory):
        """Already cancelled tasks are skipped, not double-cancelled."""
        from app.services.task_service import TaskService

        t1 = await _create_task(
            test_session_factory, USER_A, "Already gone",
            status=TaskStatus.CANCELLED,
        )

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[t1.id],
        )

        assert result["success"] is False
        assert result["cancelled_count"] == 0
        assert len(result["skipped_tasks"]) == 1
        assert "cancelled" in result["skipped_tasks"][0]["reason"].lower()

    async def test_completed_tasks_are_skipped(self, test_session_factory):
        """Completed tasks are skipped, not cancelled."""
        from app.services.task_service import TaskService

        t1 = await _create_task(
            test_session_factory, USER_A, "Done task",
            status=TaskStatus.COMPLETED,
        )

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[t1.id],
        )

        assert result["success"] is False
        assert result["cancelled_count"] == 0
        assert len(result["skipped_tasks"]) == 1
        assert "completed" in result["skipped_tasks"][0]["reason"].lower()

    async def test_mixed_valid_and_invalid_ids(self, test_session_factory):
        """Mix of valid, invalid, and non-cancellable IDs."""
        from app.services.task_service import TaskService

        valid = await _create_task(test_session_factory, USER_A, "Cancel me")
        completed = await _create_task(
            test_session_factory, USER_A, "Done",
            status=TaskStatus.COMPLETED,
        )

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[valid.id, completed.id, 99999],
        )

        assert result["success"] is True
        assert result["cancelled_count"] == 1
        assert result["cancelled_tasks"][0]["task_id"] == valid.id
        assert len(result["skipped_tasks"]) == 1
        assert len(result["not_found_tasks"]) == 1

    async def test_duplicate_task_ids_are_deduplicated(self, test_session_factory):
        """Duplicate IDs in the input should be deduplicated."""
        from app.services.task_service import TaskService

        t1 = await _create_task(test_session_factory, USER_A, "Dedupe me")

        result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[t1.id, t1.id, t1.id],
        )

        assert result["success"] is True
        assert result["cancelled_count"] == 1


# ──────────────────────────────────────────────
# Part 2: DailyPlanService excludes cancelled tasks
# ──────────────────────────────────────────────

class TestDailyPlanExcludesCancelledTasks:
    """Verify DailyPlanService no longer returns batch-cancelled tasks."""

    async def test_cancelled_tasks_excluded_from_daily_plan(self, test_session_factory):
        """After batch cancel, tasks should not appear in Daily Planner."""
        from app.services.task_service import TaskService
        from app.services.daily_plan_service import DailyPlanService

        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        overdue = await _create_task(
            test_session_factory, USER_A, "Overdue task", due_date=yesterday,
        )
        today_task = await _create_task(
            test_session_factory, USER_A, "Today task", due_date=now,
        )

        # Cancel both via batch
        cancel_result = await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[overdue.id, today_task.id],
        )
        assert cancel_result["cancelled_count"] == 2

        # Now get daily plan — should show zero tasks
        plan_result = await DailyPlanService.get_daily_plan(
            telegram_user_id=USER_A,
            target_date=now.strftime("%Y-%m-%d"),
        )

        assert plan_result["success"] is True
        assert plan_result["scheduled_count"] == 0
        assert plan_result["overdue_count"] == 0
        assert plan_result["total_tasks"] == 0

    async def test_future_tasks_survive_overdue_cleanup(self, test_session_factory):
        """Cancelling overdue tasks should not affect future tasks."""
        from app.services.task_service import TaskService
        from app.services.daily_plan_service import DailyPlanService

        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        overdue = await _create_task(
            test_session_factory, USER_A, "Old task", due_date=yesterday,
        )
        future = await _create_task(
            test_session_factory, USER_A, "Future task", due_date=tomorrow,
        )

        # Cancel only the overdue task
        await TaskService.batch_cancel_tasks(
            telegram_user_id=USER_A,
            task_ids=[overdue.id],
        )

        # Daily plan for tomorrow should still include the future task
        plan = await DailyPlanService.get_daily_plan(
            telegram_user_id=USER_A,
            target_date=tomorrow.strftime("%Y-%m-%d"),
        )

        assert plan["success"] is True
        assert plan["scheduled_count"] == 1
        assert plan["scheduled_tasks"][0]["task_id"] == future.id
        assert plan["overdue_count"] == 0  # The overdue was cancelled


# ──────────────────────────────────────────────
# Part 3: Tool executor wiring
# ──────────────────────────────────────────────

class TestBatchCancelToolWiring:
    """Verify the tool declaration and executor are properly wired."""

    def test_batch_cancel_tool_exists_in_declarations(self):
        """batch_cancel_tasks should be a registered FunctionDeclaration."""
        from app.ai.tools import TASK_TOOLS

        tool_names = [
            fd.name for fd in TASK_TOOLS.function_declarations
        ]
        assert "batch_cancel_tasks" in tool_names

    def test_batch_cancel_tool_requires_task_ids(self):
        """batch_cancel_tasks schema should require task_ids parameter."""
        from app.ai.tools import TASK_TOOLS

        batch_tool = None
        for fd in TASK_TOOLS.function_declarations:
            if fd.name == "batch_cancel_tasks":
                batch_tool = fd
                break

        assert batch_tool is not None
        assert "task_ids" in batch_tool.parameters.required

    async def test_execute_tool_dispatches_batch_cancel(self):
        """execute_tool should route 'batch_cancel_tasks' to TaskService."""
        from app.ai.tools import execute_tool

        mock_result = {
            "success": True,
            "cancelled_count": 2,
            "cancelled_tasks": [],
            "skipped_tasks": [],
            "not_found_tasks": [],
        }

        with patch(
            "app.ai.tools.TaskService.batch_cancel_tasks",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_batch:
            result = await execute_tool(
                tool_name="batch_cancel_tasks",
                tool_args={"task_ids": [1, 2, 3]},
                telegram_user_id=USER_A,
            )

            mock_batch.assert_called_once_with(
                telegram_user_id=USER_A,
                task_ids=[1, 2, 3],
            )
            assert result["success"] is True

    async def test_execute_tool_filters_invalid_ids(self):
        """execute_tool should filter out zero/negative IDs before calling TaskService."""
        from app.ai.tools import execute_tool

        with patch(
            "app.ai.tools.TaskService.batch_cancel_tasks",
            new_callable=AsyncMock,
            return_value={
                "success": False, "cancelled_count": 0,
                "cancelled_tasks": [], "skipped_tasks": [],
                "not_found_tasks": [],
                "error": "Daftar task_ids kosong. Tidak ada tugas yang dibatalkan.",
            },
        ) as mock_batch:
            await execute_tool(
                tool_name="batch_cancel_tasks",
                tool_args={"task_ids": [0, -1]},
                telegram_user_id=USER_A,
            )

            # All invalid IDs should be filtered out, passing empty list
            mock_batch.assert_called_once_with(
                telegram_user_id=USER_A,
                task_ids=[],
            )


# ──────────────────────────────────────────────
# Part 4: Anti-hallucination guardrail
# ──────────────────────────────────────────────

class TestAntiHallucinationGuardrail:
    """Verify the system prompt contains anti-hallucination rules."""

    def test_system_prompt_contains_anti_hallucination_rule(self):
        """System prompt should instruct the AI to never fabricate success."""
        from app.ai.agent import _get_agent_system_prompt

        prompt = _get_agent_system_prompt()

        # Check anti-hallucination rule
        assert "JANGAN PERNAH mengklaim" in prompt
        assert "success=true" in prompt
        assert "mengarang task_id" in prompt

    def test_system_prompt_contains_batch_cleanup_flow(self):
        """System prompt should instruct the proper batch cleanup flow."""
        from app.ai.agent import _get_agent_system_prompt

        prompt = _get_agent_system_prompt()

        # Check batch flow instructions
        assert "batch_cancel_tasks" in prompt
        assert "list_tasks" in prompt
        assert "klarifikasi" in prompt

    def test_system_prompt_preserves_existing_rules(self):
        """Existing system prompt rules should not be broken."""
        from app.ai.agent import _get_agent_system_prompt

        prompt = _get_agent_system_prompt()

        # Existing rules should still be present
        assert "AI Secretary" in prompt
        assert "generate_daily_plan" in prompt
        assert "get_productivity_statistics" in prompt
        assert "Long-Term Memory" in prompt
        assert "save_memory" in prompt


# ──────────────────────────────────────────────
# Part 5: Regression — existing cancel_task still works
# ──────────────────────────────────────────────

class TestSingleCancelStillWorks:
    """Existing cancel_task behavior must not regress."""

    async def test_single_cancel_still_works(self, test_session_factory):
        """The existing cancel_task method should still function correctly."""
        from app.services.task_service import TaskService

        task = await _create_task(test_session_factory, USER_A, "Single cancel")

        result = await TaskService.cancel_task(
            telegram_user_id=USER_A,
            task_id=task.id,
        )

        assert result["success"] is True
        assert result["task_id"] == task.id
        assert result["status"] == "cancelled"

    def test_cancel_task_tool_still_exists(self):
        """The original cancel_task tool declaration should still exist."""
        from app.ai.tools import TASK_TOOLS

        tool_names = [
            fd.name for fd in TASK_TOOLS.function_declarations
        ]
        assert "cancel_task" in tool_names
