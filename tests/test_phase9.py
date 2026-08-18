"""
Tests for Phase 9 — History & Statistics.

Covers:
1. HistoryService logic and date range handling.
2. Metrics calculation (completion rate, overdue, daily aggregation).
3. User isolation.
4. Tool definition for get_productivity_statistics.
5. Tool routing and execution.
6. Agent system prompt updates.
7. Phase 0-8 regressions.
"""

import pytest
from datetime import datetime, timedelta, time
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

from app.services.history_service import HistoryService
from app.ai.tools import TASK_TOOLS, execute_tool
from app.ai.agent import _get_agent_system_prompt
from app.ai.prompts import get_system_prompt

TZ = ZoneInfo("Asia/Jakarta")


# ── Helpers ───────────────────────────────────

def _make_mock_task(
    task_id=1,
    user_id=12345,
    title="Test Task",
    status="completed",
    created_at=None,
    due_date=None,
    completed_at=None,
):
    task = MagicMock()
    task.id = task_id
    task.telegram_user_id = user_id
    task.title = title
    task.status = MagicMock(value=status)
    task.created_at = created_at or datetime.now(TZ)
    task.due_date = due_date
    task.completed_at = completed_at
    return task


def _fake_session_with(tasks=None):
    tasks = tasks or []
    mock_session = AsyncMock()

    async def fake_execute(query):
        result = MagicMock()
        result.scalars.return_value.all.return_value = tasks
        return result

    mock_session.execute = fake_execute

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    return fake_session


# ── HistoryService Tests ─────────────────────

class TestHistoryService:
    @pytest.mark.asyncio
    async def test_empty_history(self):
        fake = _fake_session_with()
        with patch("app.services.history_service.get_db_session", fake):
            result = await HistoryService.get_statistics(telegram_user_id=123)
            
        assert result["success"] is True
        assert result["total_tasks"] == 0
        assert result["completed"] == 0
        assert result["pending"] == 0
        assert result["completion_rate_percent"] == 0
        assert result["most_productive_day"] is None

    @pytest.mark.asyncio
    async def test_invalid_date_returns_error(self):
        result = await HistoryService.get_statistics(
            telegram_user_id=123,
            start_date="invalid-date"
        )
        assert result["success"] is False
        assert "tidak valid" in result["error"]

    @pytest.mark.asyncio
    async def test_basic_metrics_calculation(self):
        now = datetime.now(TZ)
        tasks = [
            _make_mock_task(status="completed", completed_at=now),
            _make_mock_task(status="completed", completed_at=now),
            _make_mock_task(status="pending", due_date=now + timedelta(days=1)),
            _make_mock_task(status="in_progress"),
            _make_mock_task(status="cancelled"),
            _make_mock_task(status="pending", due_date=now - timedelta(days=1)),  # overdue
        ]
        
        fake = _fake_session_with(tasks)
        with patch("app.services.history_service.get_db_session", fake):
            result = await HistoryService.get_statistics(telegram_user_id=123)
            
        assert result["total_tasks"] == 6
        assert result["completed"] == 2
        assert result["pending"] == 2
        assert result["in_progress"] == 1
        assert result["cancelled"] == 1
        assert result["overdue"] == 1
        # Active total = 6 - 1 = 5. Completed = 2. 2/5 = 40%
        assert result["completion_rate_percent"] == 40
        assert result["most_productive_day"] == now.date().isoformat()
        assert result["max_completed_in_a_day"] == 2

    @pytest.mark.asyncio
    async def test_daily_aggregation(self):
        day1 = datetime(2026, 8, 1, 12, 0, tzinfo=TZ)
        day2 = datetime(2026, 8, 2, 12, 0, tzinfo=TZ)
        
        tasks = [
            _make_mock_task(status="completed", completed_at=day1),
            _make_mock_task(status="completed", completed_at=day1),
            _make_mock_task(status="completed", completed_at=day1),
            _make_mock_task(status="completed", completed_at=day2),
        ]
        
        fake = _fake_session_with(tasks)
        with patch("app.services.history_service.get_db_session", fake):
            result = await HistoryService.get_statistics(telegram_user_id=123)
            
        assert result["completed_by_day"]["2026-08-01"] == 3
        assert result["completed_by_day"]["2026-08-02"] == 1
        assert result["most_productive_day"] == "2026-08-01"

    @pytest.mark.asyncio
    async def test_date_range_filters(self):
        # We test that the query is constructed properly.
        mock_session = AsyncMock()
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

        with patch("app.services.history_service.get_db_session", fake_session):
            await HistoryService.get_statistics(
                telegram_user_id=123,
                start_date="2026-08-01",
                end_date="2026-08-07"
            )
            
        assert len(calls) == 1
        query_str = str(calls[0])
        # The query should contain constraints on created_at, due_date, completed_at
        assert "created_at >=" in query_str or "created_at <=" in query_str
        assert "telegram_user_id" in query_str


# ── Tool & Agent Tests ───────────────────────

class TestPhase9AIIntegration:
    def test_statistics_tool_exists(self):
        names = [fd.name for fd in TASK_TOOLS.function_declarations]
        assert "get_productivity_statistics" in names

    def test_statistics_tool_has_parameters(self):
        fd = next(
            f for f in TASK_TOOLS.function_declarations
            if f.name == "get_productivity_statistics"
        )
        assert "start_date" in fd.parameters.properties
        assert "end_date" in fd.parameters.properties

    @pytest.mark.asyncio
    async def test_execute_tool_routes_to_history(self):
        with patch(
            "app.ai.tools.HistoryService.get_statistics",
            new_callable=AsyncMock,
            return_value={"success": True, "total_tasks": 10},
        ) as mock_history:
            result = await execute_tool(
                tool_name="get_productivity_statistics",
                tool_args={"start_date": "2026-08-01", "end_date": "2026-08-07"},
                telegram_user_id=123,
            )
            mock_history.assert_called_once_with(
                telegram_user_id=123,
                start_date="2026-08-01",
                end_date="2026-08-07",
            )
            assert result["success"] is True
            assert result["total_tasks"] == 10

    def test_agent_prompt_instructs_statistics_tool(self):
        prompt = _get_agent_system_prompt()
        assert "get_productivity_statistics" in prompt
        assert "statistik" in prompt.lower() or "produktivitas" in prompt.lower()

    def test_prompts_active_capability(self):
        prompt = get_system_prompt()
        assert "Phase 9" in prompt
        assert "aktif" in prompt.lower()


# ── Phase 0-8 Regression Tests ────────────────

class TestPhase08Regressions:
    def test_services_export(self):
        from app.services import HistoryService as HS, EveningReviewService as ERS, MorningBriefService as MBS, TaskService
        assert HS is HistoryService
        assert ERS is not None
        assert MBS is not None
        assert TaskService is not None

    def test_original_six_tools_intact(self):
        names = [fd.name for fd in TASK_TOOLS.function_declarations]
        for expected in ["create_task", "list_tasks", "update_task",
                         "complete_task", "cancel_task", "generate_daily_plan"]:
            assert expected in names
