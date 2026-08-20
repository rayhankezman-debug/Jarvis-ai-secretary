"""
Tests for Phase 5 — Reminder Engine.

Covers: ReminderService logic, ReminderType enum, Reminder dataclass,
SchedulerEngine lifecycle, duplicate prevention, Telegram notification,
reminder timing thresholds, and Phase 0-4 regressions.

All DB calls and Telegram sends are mocked — no real API calls.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from app.scheduler.reminder_service import (
    ReminderService,
    ReminderType,
    Reminder,
)
from app.scheduler.engine import (
    SchedulerEngine,
    get_scheduler,
    set_scheduler,
    reset_scheduler,
)

TZ = ZoneInfo("Asia/Jakarta")


# ── Fixtures ──────────────────────────────────

@pytest.fixture
def reminder_service():
    """Fresh ReminderService with no sent history."""
    return ReminderService()


@pytest.fixture
def mock_task():
    """Create a mock Task with sensible defaults."""
    def _make(
        task_id=1,
        user_id=12345,
        title="Test Task",
        due_date=None,
        status_value="pending",
        created_at=None,
    ):
        task = MagicMock()
        task.id = task_id
        task.telegram_user_id = user_id
        task.title = title
        task.due_date = due_date
        task.status = MagicMock(value=status_value)
        if created_at is None:
            task.created_at = datetime.now(TZ) - timedelta(days=30)
        else:
            task.created_at = created_at
        return task
    return _make


# ── ReminderType Enum Tests ───────────────────

class TestReminderType:
    def test_h7_value(self):
        assert ReminderType.H7.value == "h7"

    def test_h3_value(self):
        assert ReminderType.H3.value == "h3"

    def test_h1_value(self):
        assert ReminderType.H1.value == "h1"

    def test_h0_value(self):
        assert ReminderType.H0.value == "h0"

    def test_due_soon_value(self):
        assert ReminderType.DUE_SOON.value == "due_soon"

    def test_overdue_value(self):
        assert ReminderType.OVERDUE.value == "overdue"

    def test_is_string_enum(self):
        assert isinstance(ReminderType.H1, str)


# ── Reminder Dataclass Tests ──────────────────

class TestReminderDataclass:
    def test_reminder_creation(self):
        now = datetime.now(TZ)
        r = Reminder(
            telegram_user_id=123,
            task_id=1,
            task_title="Olahraga",
            task_due_date=now,
            reminder_type=ReminderType.H0,
            message="Test message",
        )
        assert r.telegram_user_id == 123
        assert r.task_id == 1
        assert r.task_title == "Olahraga"
        assert r.reminder_type == ReminderType.H0
        assert r.message == "Test message"


# ── ReminderService Sent Tracking Tests ───────

class TestReminderServiceTracking:
    def test_initial_state_empty(self, reminder_service):
        assert not reminder_service.has_been_sent(1, ReminderType.H0)

    def test_mark_sent(self, reminder_service):
        reminder_service.mark_sent(1, ReminderType.H0)
        assert reminder_service.has_been_sent(1, ReminderType.H0)

    def test_different_type_not_sent(self, reminder_service):
        reminder_service.mark_sent(1, ReminderType.H0)
        assert not reminder_service.has_been_sent(1, ReminderType.H1)

    def test_different_task_not_sent(self, reminder_service):
        reminder_service.mark_sent(1, ReminderType.H0)
        assert not reminder_service.has_been_sent(2, ReminderType.H0)

    def test_clear_sent(self, reminder_service):
        reminder_service.mark_sent(1, ReminderType.H0)
        reminder_service.mark_sent(2, ReminderType.H1)
        reminder_service.clear_sent()
        assert not reminder_service.has_been_sent(1, ReminderType.H0)
        assert not reminder_service.has_been_sent(2, ReminderType.H1)

    def test_cleanup_completed_tasks(self, reminder_service):
        reminder_service.mark_sent(1, ReminderType.H0)
        reminder_service.mark_sent(2, ReminderType.H1)
        reminder_service.mark_sent(3, ReminderType.DUE_SOON)
        reminder_service.cleanup_completed_tasks({1, 3})
        assert not reminder_service.has_been_sent(1, ReminderType.H0)
        assert reminder_service.has_been_sent(2, ReminderType.H1)
        assert not reminder_service.has_been_sent(3, ReminderType.DUE_SOON)


# ── ReminderService Evaluate Logic Tests ──────

class TestReminderServiceEvaluate:
    """Test the _evaluate_task method with different time offsets."""

    def test_h1_reminder_36h_before(self, reminder_service, mock_task):
        """Task due in 36 hours should trigger H-1 reminder."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=36)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.H1

    def test_h0_reminder_12h_before(self, reminder_service, mock_task):
        """Task due in 12 hours should trigger H-0 reminder."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=12)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.H0

    def test_due_soon_15min_before(self, reminder_service, mock_task):
        """Task due in 15 minutes should trigger DUE_SOON reminder."""
        now = datetime.now(TZ)
        due = now + timedelta(minutes=15)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.DUE_SOON

    def test_overdue_past_due(self, reminder_service, mock_task):
        """Task past due date should trigger OVERDUE reminder."""
        now = datetime.now(TZ)
        due = now - timedelta(hours=1)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.OVERDUE

    def test_no_reminder_far_future(self, reminder_service, mock_task):
        """Task due in 10 days should not trigger any reminder."""
        now = datetime.now(TZ)
        due = now + timedelta(days=10)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 0

    def test_h7_reminder_6days_before(self, reminder_service, mock_task):
        """Task due in 6 days should trigger H-7 reminder."""
        now = datetime.now(TZ)
        due = now + timedelta(days=6)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.H7

    def test_h3_reminder_2days_before(self, reminder_service, mock_task):
        """Task due in 2.5 days should trigger H-3 reminder."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=60) # 2.5 days
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.H3

    def test_retroactive_h7_skipped(self, reminder_service, mock_task):
        """Task created after H-7 window should skip H-7 reminder."""
        now = datetime.now(TZ)
        due = now + timedelta(days=6)
        # Created 5.5 days before due (after H-7 window)
        created_at = due - timedelta(days=5, hours=12)
        task = mock_task(due_date=due, created_at=created_at)

        reminders = reminder_service._evaluate_task(task, now)
        # Should be empty because it skips H-7 and it's too early for H-3
        assert len(reminders) == 0

    def test_retroactive_h3_skipped(self, reminder_service, mock_task):
        """Task created after H-3 window should skip H-3 reminder."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=60) # 2.5 days
        # Created 2 days before due (after H-3 window)
        created_at = due - timedelta(days=2)
        task = mock_task(due_date=due, created_at=created_at)

        reminders = reminder_service._evaluate_task(task, now)
        # Should be empty because it skips H-3 and it's too early for H-1
        assert len(reminders) == 0

    def test_no_duplicate_after_mark_sent(self, reminder_service, mock_task):
        """Once marked as sent, the same reminder should not be generated again."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=12)
        task = mock_task(due_date=due)

        # First check — should generate reminder
        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        reminder_service.mark_sent(task.id, reminders[0].reminder_type)

        # Second check — should not generate duplicate
        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 0

    def test_reminder_message_contains_title(self, reminder_service, mock_task):
        """Reminder message should contain the task title."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=12)
        task = mock_task(title="Kuliah Pagi")

        task.due_date = due
        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert "Kuliah Pagi" in reminders[0].message

    def test_reminder_contains_user_id(self, reminder_service, mock_task):
        """Reminder should carry the task owner's Telegram user ID."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=12)
        task = mock_task(user_id=99999, due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert reminders[0].telegram_user_id == 99999

    def test_h1_boundary_exactly_48h(self, reminder_service, mock_task):
        """Task due in exactly 48 hours is at the boundary — should trigger H-1."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=48)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.H1

    def test_h0_boundary_exactly_24h(self, reminder_service, mock_task):
        """Task due in exactly 24 hours is at the boundary — should trigger H-0."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=24)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.H0

    def test_due_soon_boundary_exactly_30min(self, reminder_service, mock_task):
        """Task due in exactly 30 min is at the boundary — should trigger DUE_SOON."""
        now = datetime.now(TZ)
        due = now + timedelta(minutes=30)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.DUE_SOON

    def test_due_soon_boundary_exactly_due(self, reminder_service, mock_task):
        """Task exactly at due time (0 hours until due) should trigger DUE_SOON."""
        now = datetime.now(TZ)
        due = now
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.DUE_SOON

    def test_overdue_boundary_just_past_due(self, reminder_service, mock_task):
        """Task just past due (-0.01 hours) should trigger OVERDUE."""
        now = datetime.now(TZ)
        due = now - timedelta(seconds=1)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.OVERDUE

    def test_h7_boundary_exactly_168h(self, reminder_service, mock_task):
        """Task due in exactly 168 hours is at the boundary — should trigger H-7."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=168)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.H7

    def test_h3_boundary_exactly_72h(self, reminder_service, mock_task):
        """Task due in exactly 72 hours is at the boundary — should trigger H-3."""
        now = datetime.now(TZ)
        due = now + timedelta(hours=72)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1
        assert reminders[0].reminder_type == ReminderType.H3

    def test_naive_due_date_handled(self, reminder_service, mock_task):
        """Tasks with naive datetime due_date should still work."""
        now = datetime.now(TZ)
        due = (now + timedelta(hours=12)).replace(tzinfo=None)
        task = mock_task(due_date=due)

        reminders = reminder_service._evaluate_task(task, now)
        assert len(reminders) == 1


# ── ReminderService DB Integration Tests ──────

class TestReminderServiceDB:
    @pytest.mark.asyncio
    async def test_check_reminders_queries_db(self, reminder_service):
        """check_reminders should query the database for active tasks."""
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.telegram_user_id = 123
        mock_task.title = "Test"
        mock_task.due_date = datetime.now(TZ) + timedelta(hours=6)
        mock_task.status = MagicMock(value="pending")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_task]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def fake_session():
            yield mock_session

        with patch("app.scheduler.reminder_service.get_db_session", fake_session):
            reminders = await reminder_service.check_reminders()

        assert len(reminders) == 1
        assert reminders[0].task_id == 1

    @pytest.mark.asyncio
    async def test_check_reminders_handles_db_error(self, reminder_service):
        """check_reminders should not crash on DB errors."""
        with patch("app.scheduler.reminder_service.get_db_session",
                    side_effect=Exception("DB down")):
            reminders = await reminder_service.check_reminders()

        assert reminders == []

    @pytest.mark.asyncio
    async def test_check_reminders_no_tasks(self, reminder_service):
        """check_reminders with no active tasks should return empty list."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def fake_session():
            yield mock_session

        with patch("app.scheduler.reminder_service.get_db_session", fake_session):
            reminders = await reminder_service.check_reminders()

        assert reminders == []


# ── SchedulerEngine Tests ─────────────────────

class TestSchedulerEngine:
    @pytest.mark.asyncio
    async def test_engine_starts_and_stops(self):
        """Scheduler should start and stop without errors."""
        engine = SchedulerEngine(bot_application=None, check_interval_minutes=60)
        await engine.start()
        assert engine.running is True
        await engine.stop()
        assert engine.running is False

    @pytest.mark.asyncio
    async def test_engine_double_start_safe(self):
        """Starting the scheduler twice should not crash."""
        engine = SchedulerEngine(bot_application=None, check_interval_minutes=60)
        await engine.start()
        await engine.start()  # Should log warning, not crash
        assert engine.running is True
        await engine.stop()

    @pytest.mark.asyncio
    async def test_engine_stop_without_start(self):
        """Stopping without starting should be a no-op."""
        engine = SchedulerEngine(bot_application=None)
        await engine.stop()  # Should not crash
        assert engine.running is False

    @pytest.mark.asyncio
    async def test_engine_has_reminder_service(self):
        """Engine should expose its ReminderService."""
        engine = SchedulerEngine(bot_application=None)
        assert isinstance(engine.reminder_service, ReminderService)
        await engine.stop()

    @pytest.mark.asyncio
    async def test_trigger_check_without_bot(self):
        """Manual trigger should find reminders but not send (no bot)."""
        engine = SchedulerEngine(bot_application=None)

        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.telegram_user_id = 123
        mock_task.title = "Test"
        mock_task.due_date = datetime.now(TZ) + timedelta(hours=6)
        mock_task.status = MagicMock(value="pending")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_task]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def fake_session():
            yield mock_session

        with patch("app.scheduler.reminder_service.get_db_session", fake_session):
            reminders = await engine.trigger_check()

        assert len(reminders) == 1
        # Without bot, mark_sent should NOT be called (send returns False)
        assert not engine.reminder_service.has_been_sent(1, ReminderType.H0)

    @pytest.mark.asyncio
    async def test_trigger_check_with_bot_sends_message(self):
        """With a bot, trigger_check should send Telegram messages."""
        mock_bot = MagicMock()
        mock_bot.bot.send_message = AsyncMock()
        engine = SchedulerEngine(bot_application=mock_bot)

        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.telegram_user_id = 123
        mock_task.title = "Meeting"
        mock_task.due_date = datetime.now(TZ) + timedelta(hours=6)
        mock_task.status = MagicMock(value="pending")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_task]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def fake_session():
            yield mock_session

        with patch("app.scheduler.reminder_service.get_db_session", fake_session):
            reminders = await engine.trigger_check()

        assert len(reminders) == 1
        mock_bot.bot.send_message.assert_called_once()
        call_kwargs = mock_bot.bot.send_message.call_args
        assert call_kwargs.kwargs["chat_id"] == 123
        assert "Meeting" in call_kwargs.kwargs["text"]
        # After successful send, should be marked as sent
        assert engine.reminder_service.has_been_sent(1, ReminderType.H0)

    @pytest.mark.asyncio
    async def test_send_failure_does_not_mark_sent(self):
        """If Telegram send fails, reminder should NOT be marked as sent."""
        mock_bot = MagicMock()
        mock_bot.bot.send_message = AsyncMock(side_effect=Exception("Network error"))
        engine = SchedulerEngine(bot_application=mock_bot)

        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.telegram_user_id = 123
        mock_task.title = "Test"
        mock_task.due_date = datetime.now(TZ) + timedelta(hours=6)
        mock_task.status = MagicMock(value="pending")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_task]
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def fake_session():
            yield mock_session

        with patch("app.scheduler.reminder_service.get_db_session", fake_session):
            reminders = await engine.trigger_check()

        assert len(reminders) == 1
        # Failed send — should NOT be marked
        assert not engine.reminder_service.has_been_sent(1, ReminderType.H0)


# ── Scheduler Singleton Tests ─────────────────

class TestSchedulerSingleton:
    def test_initial_state_is_none(self):
        reset_scheduler()
        assert get_scheduler() is None

    def test_set_and_get(self):
        engine = SchedulerEngine(bot_application=None)
        set_scheduler(engine)
        assert get_scheduler() is engine
        reset_scheduler()

    def test_reset_clears(self):
        engine = SchedulerEngine(bot_application=None)
        set_scheduler(engine)
        reset_scheduler()
        assert get_scheduler() is None


# ── Reminder Tick Tests ───────────────────────

class TestReminderTick:
    @pytest.mark.asyncio
    async def test_tick_with_no_reminders(self):
        """Tick should handle no-reminders case gracefully."""
        engine = SchedulerEngine(bot_application=None)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def fake_session():
            yield mock_session

        with patch("app.scheduler.reminder_service.get_db_session", fake_session):
            await engine._reminder_tick()
        # No error should be raised

    @pytest.mark.asyncio
    async def test_tick_handles_exception(self):
        """Tick should catch and log exceptions without crashing."""
        engine = SchedulerEngine(bot_application=None)

        with patch.object(
            engine._reminder_service, "check_reminders",
            new_callable=AsyncMock, side_effect=Exception("Unexpected"),
        ):
            await engine._reminder_tick()
        # Should not raise


# ── User Isolation Tests ──────────────────────

class TestReminderUserIsolation:
    def test_reminders_carry_correct_user_id(self, reminder_service, mock_task):
        """Each reminder should carry the task owner's Telegram user ID."""
        now = datetime.now(TZ)

        task_a = mock_task(task_id=1, user_id=111, due_date=now + timedelta(hours=6))
        task_b = mock_task(task_id=2, user_id=222, due_date=now + timedelta(hours=6))

        reminders_a = reminder_service._evaluate_task(task_a, now)
        reminders_b = reminder_service._evaluate_task(task_b, now)

        assert reminders_a[0].telegram_user_id == 111
        assert reminders_b[0].telegram_user_id == 222


# ── Phase 0-4 Regression Tests ────────────────

class TestPhase04Regression:
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

    def test_tool_definitions_intact(self):
        from app.ai.tools import TASK_TOOLS
        names = [fd.name for fd in TASK_TOOLS.function_declarations]
        assert "create_task" in names
        assert "list_tasks" in names

    def test_agent_singleton_reset_works(self):
        from app.ai.agent import reset_agent
        import app.ai.agent
        reset_agent()
        assert app.ai.agent._agent_instance is None

    @pytest.mark.asyncio
    async def test_task_service_validates_empty_title(self):
        """TaskService should reject empty titles."""
        from app.services.task_service import TaskService
        result = await TaskService.create_task(
            telegram_user_id=1, title=""
        )
        assert result["success"] is False
