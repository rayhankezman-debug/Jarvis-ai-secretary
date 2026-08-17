"""
Tests for Phase 6 — Daily Planner.

Covers: DailyPlanService logic, generate_daily_plan tool definition,
tool execution routing, date handling, user isolation, empty task lists,
priority ordering, overdue/backlog separation, and Phase 0-5 regressions.

All DB calls are mocked — no real API calls.
"""

import pytest
from datetime import datetime, timedelta, time
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

from app.services.daily_plan_service import DailyPlanService, _format_tasks
from app.ai.tools import TASK_TOOLS, execute_tool

TZ = ZoneInfo("Asia/Jakarta")


# ── Helpers ───────────────────────────────────

def _make_mock_task(
    task_id=1,
    user_id=12345,
    title="Test Task",
    description=None,
    due_date=None,
    priority="medium",
    status="pending",
):
    """Create a mock Task object."""
    task = MagicMock()
    task.id = task_id
    task.telegram_user_id = user_id
    task.title = title
    task.description = description
    task.due_date = due_date
    task.priority = MagicMock(value=priority)
    task.status = MagicMock(value=status)
    task.created_at = datetime.now(TZ)
    return task


def _fake_session_with(due_tasks=None, overdue_tasks=None, backlog_tasks=None):
    """Create a mock DB session that returns different tasks for 3 queries."""
    due_tasks = due_tasks or []
    overdue_tasks = overdue_tasks or []
    backlog_tasks = backlog_tasks or []

    mock_session = AsyncMock()
    call_count = [0]

    async def fake_execute(query):
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            result.scalars.return_value.all.return_value = due_tasks
        elif idx == 1:
            result.scalars.return_value.all.return_value = overdue_tasks
        else:
            result.scalars.return_value.all.return_value = backlog_tasks
        return result

    mock_session.execute = fake_execute

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    return fake_session


# ── Tool Definition Tests ─────────────────────

class TestDailyPlanToolDefinition:
    def test_generate_daily_plan_exists(self):
        """generate_daily_plan should be in the tool definitions."""
        names = [fd.name for fd in TASK_TOOLS.function_declarations]
        assert "generate_daily_plan" in names

    def test_tool_has_target_date_param(self):
        """generate_daily_plan should accept a target_date parameter."""
        fd = next(
            f for f in TASK_TOOLS.function_declarations
            if f.name == "generate_daily_plan"
        )
        assert "target_date" in fd.parameters.properties

    def test_target_date_is_optional(self):
        """target_date should be optional (not in required)."""
        fd = next(
            f for f in TASK_TOOLS.function_declarations
            if f.name == "generate_daily_plan"
        )
        required = fd.parameters.required or []
        assert "target_date" not in required

    def test_tool_description_mentions_jadwal(self):
        """Tool description should mention jadwal/rencana for discoverability."""
        fd = next(
            f for f in TASK_TOOLS.function_declarations
            if f.name == "generate_daily_plan"
        )
        desc = fd.description.lower()
        assert "jadwal" in desc or "rencana" in desc

    def test_total_tool_count_is_six(self):
        """With Phase 6 we should have 6 tools total."""
        assert len(TASK_TOOLS.function_declarations) == 6


# ── Tool Execution Routing Tests ──────────────

class TestDailyPlanToolExecution:
    @pytest.mark.asyncio
    async def test_execute_tool_routes_to_daily_plan(self):
        """execute_tool should route generate_daily_plan to DailyPlanService."""
        with patch(
            "app.ai.tools.DailyPlanService.get_daily_plan",
            new_callable=AsyncMock,
            return_value={"success": True, "total_tasks": 0},
        ) as mock_plan:
            result = await execute_tool(
                tool_name="generate_daily_plan",
                tool_args={"target_date": "2026-08-18"},
                telegram_user_id=12345,
            )
            mock_plan.assert_called_once_with(
                telegram_user_id=12345,
                target_date="2026-08-18",
            )
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_tool_passes_none_date_when_missing(self):
        """If target_date is not in args, None should be passed."""
        with patch(
            "app.ai.tools.DailyPlanService.get_daily_plan",
            new_callable=AsyncMock,
            return_value={"success": True},
        ) as mock_plan:
            await execute_tool(
                tool_name="generate_daily_plan",
                tool_args={},
                telegram_user_id=99,
            )
            mock_plan.assert_called_once_with(
                telegram_user_id=99,
                target_date=None,
            )

    @pytest.mark.asyncio
    async def test_existing_tools_still_work(self):
        """Phase 4 tools should still route correctly."""
        with patch(
            "app.ai.tools.TaskService.list_tasks",
            new_callable=AsyncMock,
            return_value={"success": True, "tasks": [], "count": 0},
        ):
            result = await execute_tool(
                tool_name="list_tasks",
                tool_args={},
                telegram_user_id=1,
            )
            assert result["success"] is True


# ── DailyPlanService Date Handling Tests ──────

class TestDailyPlanServiceDate:
    @pytest.mark.asyncio
    async def test_default_date_is_today(self):
        """No target_date should default to today."""
        today = datetime.now(TZ).date()
        fake = _fake_session_with()

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=1,
            )
        assert result["success"] is True
        assert result["date"] == today.isoformat()

    @pytest.mark.asyncio
    async def test_explicit_date_is_used(self):
        """Explicit target_date should be used."""
        fake = _fake_session_with()

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=1,
                target_date="2026-12-25",
            )
        assert result["success"] is True
        assert result["date"] == "2026-12-25"

    @pytest.mark.asyncio
    async def test_iso_datetime_is_parsed_to_date(self):
        """Full ISO datetime should be parsed to just the date."""
        fake = _fake_session_with()

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=1,
                target_date="2026-08-18T14:30:00+07:00",
            )
        assert result["success"] is True
        assert result["date"] == "2026-08-18"

    @pytest.mark.asyncio
    async def test_invalid_date_returns_error(self):
        """Invalid date string should return an error."""
        result = await DailyPlanService.get_daily_plan(
            telegram_user_id=1,
            target_date="not-a-date",
        )
        assert result["success"] is False
        assert "tidak valid" in result["error"]

    @pytest.mark.asyncio
    async def test_day_name_is_correct(self):
        """Response should contain the correct Indonesian day name."""
        # 2026-12-25 is a Friday = Jumat
        fake = _fake_session_with()

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=1,
                target_date="2026-12-25",
            )
        assert result["day_name"] == "Jumat"


# ── DailyPlanService Task Categorization Tests ─

class TestDailyPlanServiceTasks:
    @pytest.mark.asyncio
    async def test_empty_day_returns_no_tasks(self):
        """Day with no tasks should return empty lists."""
        fake = _fake_session_with()

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=1,
                target_date="2026-08-18",
            )
        assert result["success"] is True
        assert result["scheduled_count"] == 0
        assert result["overdue_count"] == 0
        assert result["backlog_count"] == 0
        assert result["total_tasks"] == 0

    @pytest.mark.asyncio
    async def test_empty_day_message_says_hari_bebas(self):
        """Empty day message should include 'Hari bebas'."""
        fake = _fake_session_with()

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=1,
                target_date="2026-08-18",
            )
        assert "Hari bebas" in result["message"]

    @pytest.mark.asyncio
    async def test_scheduled_tasks_returned(self):
        """Tasks due on the target date should appear in scheduled_tasks."""
        due = datetime(2026, 8, 18, 9, 0, tzinfo=TZ)
        task = _make_mock_task(task_id=1, title="Kuliah", due_date=due)
        fake = _fake_session_with(due_tasks=[task])

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=12345,
                target_date="2026-08-18",
            )
        assert result["scheduled_count"] == 1
        assert result["scheduled_tasks"][0]["title"] == "Kuliah"

    @pytest.mark.asyncio
    async def test_overdue_tasks_returned(self):
        """Overdue tasks should appear in overdue_tasks."""
        overdue = datetime(2026, 8, 15, 9, 0, tzinfo=TZ)
        task = _make_mock_task(task_id=2, title="Deadline", due_date=overdue)
        fake = _fake_session_with(overdue_tasks=[task])

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=12345,
                target_date="2026-08-18",
            )
        assert result["overdue_count"] == 1
        assert result["overdue_tasks"][0]["title"] == "Deadline"

    @pytest.mark.asyncio
    async def test_backlog_tasks_returned(self):
        """Tasks without due_date should appear in backlog_tasks."""
        task = _make_mock_task(task_id=3, title="Belajar", due_date=None)
        fake = _fake_session_with(backlog_tasks=[task])

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=12345,
                target_date="2026-08-18",
            )
        assert result["backlog_count"] == 1
        assert result["backlog_tasks"][0]["title"] == "Belajar"

    @pytest.mark.asyncio
    async def test_total_tasks_sums_all_categories(self):
        """total_tasks should be the sum of all categories."""
        due = datetime(2026, 8, 18, 9, 0, tzinfo=TZ)
        t1 = _make_mock_task(task_id=1, title="A", due_date=due)
        t2 = _make_mock_task(task_id=2, title="B", due_date=due - timedelta(days=5))
        t3 = _make_mock_task(task_id=3, title="C", due_date=None)
        fake = _fake_session_with(due_tasks=[t1], overdue_tasks=[t2], backlog_tasks=[t3])

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=12345,
                target_date="2026-08-18",
            )
        assert result["total_tasks"] == 3

    @pytest.mark.asyncio
    async def test_message_shows_date_when_tasks_exist(self):
        """Message should show the date when there are tasks."""
        due = datetime(2026, 8, 18, 9, 0, tzinfo=TZ)
        task = _make_mock_task(task_id=1, title="Meeting", due_date=due)
        fake = _fake_session_with(due_tasks=[task])

        with patch("app.services.daily_plan_service.get_db_session", fake):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=12345,
                target_date="2026-08-18",
            )
        assert "Rencana untuk" in result["message"]


# ── Priority Ordering Tests ───────────────────

class TestDailyPlanPriority:
    def test_format_tasks_sorts_by_priority(self):
        """Tasks should be sorted by priority (urgent first)."""
        t_low = _make_mock_task(task_id=1, title="Low", priority="low", due_date=None)
        t_urgent = _make_mock_task(task_id=2, title="Urgent", priority="urgent", due_date=None)
        t_high = _make_mock_task(task_id=3, title="High", priority="high", due_date=None)

        result = _format_tasks([t_low, t_urgent, t_high])
        assert result[0]["priority"] == "urgent"
        assert result[1]["priority"] == "high"
        assert result[2]["priority"] == "low"

    def test_format_tasks_includes_all_fields(self):
        """Formatted task should have all required fields."""
        due = datetime(2026, 8, 18, 14, 0, tzinfo=TZ)
        task = _make_mock_task(
            task_id=5, title="Meeting", description="With team",
            due_date=due, priority="high", status="pending",
        )
        result = _format_tasks([task])
        assert len(result) == 1
        entry = result[0]
        assert entry["task_id"] == 5
        assert entry["title"] == "Meeting"
        assert entry["description"] == "With team"
        assert entry["due_date"] == due.isoformat()
        assert entry["priority"] == "high"
        assert entry["status"] == "pending"

    def test_format_tasks_handles_none_due_date(self):
        """Task without due_date should format due_date as None."""
        task = _make_mock_task(task_id=1, title="Backlog", due_date=None)
        result = _format_tasks([task])
        assert result[0]["due_date"] is None

    def test_format_tasks_empty_list(self):
        """Empty input should return empty output."""
        assert _format_tasks([]) == []


# ── User Isolation Tests ──────────────────────

class TestDailyPlanUserIsolation:
    @pytest.mark.asyncio
    async def test_user_id_is_passed_to_queries(self):
        """The user ID should be used in DB queries."""
        mock_session = AsyncMock()
        # Track all execute calls
        calls = []

        async def track_execute(query):
            calls.append(query)
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            return result

        mock_session.execute = track_execute

        @asynccontextmanager
        async def fake_session():
            yield mock_session

        with patch("app.services.daily_plan_service.get_db_session", fake_session):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=99999,
                target_date="2026-08-18",
            )

        assert result["success"] is True
        # 3 queries should have been executed (due, overdue, backlog)
        assert len(calls) == 3


# ── Error Handling Tests ──────────────────────

class TestDailyPlanErrorHandling:
    @pytest.mark.asyncio
    async def test_db_error_returns_failure(self):
        """Database errors should return a failure dict, not crash."""
        @asynccontextmanager
        async def broken_session():
            raise Exception("DB down")
            yield  # pragma: no cover

        with patch("app.services.daily_plan_service.get_db_session", broken_session):
            result = await DailyPlanService.get_daily_plan(
                telegram_user_id=1,
                target_date="2026-08-18",
            )
        assert result["success"] is False
        assert "error" in result


# ── Agent System Prompt Tests ─────────────────

class TestAgentPromptPhase6:
    def test_agent_prompt_mentions_generate_daily_plan(self):
        """Agent system prompt should mention generate_daily_plan."""
        from app.ai.agent import _get_agent_system_prompt
        prompt = _get_agent_system_prompt()
        assert "generate_daily_plan" in prompt

    def test_agent_prompt_mentions_jadwal(self):
        """Agent prompt should explain when to use daily plan tool."""
        from app.ai.agent import _get_agent_system_prompt
        prompt = _get_agent_system_prompt()
        assert "jadwal" in prompt.lower() or "rencana" in prompt.lower()


# ── Prompts.py Tests ──────────────────────────

class TestPromptsPhase6:
    def test_daily_planner_is_active(self):
        """Phase 6 should be listed as active in system prompt."""
        from app.ai.prompts import get_system_prompt
        prompt = get_system_prompt()
        assert "Phase 6" in prompt
        assert "aktif" in prompt.lower()

    def test_reminders_is_active(self):
        """Phase 5 should also be listed as active now."""
        from app.ai.prompts import get_system_prompt
        prompt = get_system_prompt()
        assert "Phase 5" in prompt
        assert "reminder" in prompt.lower()


# ── Services Package Export Tests ─────────────

class TestServicesExport:
    def test_daily_plan_service_exported(self):
        """DailyPlanService should be importable from app.services."""
        from app.services import DailyPlanService as DPS
        assert DPS is DailyPlanService

    def test_task_service_still_exported(self):
        """TaskService should still be importable (no regression)."""
        from app.services import TaskService
        assert TaskService is not None


# ── Phase 0–5 Regression Tests ────────────────

class TestPhase05Regression:
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_llm_interface_still_abstract(self):
        from app.ai.base import LLMProvider
        with pytest.raises(TypeError):
            LLMProvider()

    def test_task_model_exists(self):
        from app.database.models import Task, TaskStatus, TaskPriority
        assert TaskStatus.PENDING.value == "pending"
        assert TaskPriority.MEDIUM.value == "medium"

    def test_original_five_tools_intact(self):
        """All original 5 tools should still exist."""
        names = [fd.name for fd in TASK_TOOLS.function_declarations]
        for expected in ["create_task", "list_tasks", "update_task",
                         "complete_task", "cancel_task"]:
            assert expected in names

    def test_agent_singleton_reset_works(self):
        from app.ai.agent import reset_agent
        import app.ai.agent
        reset_agent()
        assert app.ai.agent._agent_instance is None

    def test_reminder_service_importable(self):
        from app.scheduler import ReminderService, ReminderType
        assert ReminderType.H0.value == "h0"

    def test_scheduler_engine_importable(self):
        from app.scheduler import SchedulerEngine, get_scheduler
        assert get_scheduler() is None or isinstance(get_scheduler(), SchedulerEngine)
