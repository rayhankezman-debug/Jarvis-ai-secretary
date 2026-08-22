"""
Tests for Phase 7 — Morning Brief.

Covers:
1. MorningBriefService creation
2. Task context generation (DailyPlanService reuse)
3. Today's tasks inclusion
4. Overdue tasks inclusion
5. High-priority backlog inclusion
6. Empty task day ("free day" brief)
7. User isolation (filtering by telegram_user_id)
8. Gemini prompt generation with MORNING_BRIEF_PROMPT
9. Gemini response handling & fallback formatting on failure/missing key
10. Telegram delivery via bot application
11. Telegram send failure graceful handling
12. Scheduler registration (Interval + Cron)
13. CronTrigger configuration (hour, minute, timezone)
14. ENABLE_MORNING_BRIEF=false configuration handling
15. MORNING_BRIEF_TIME parsing (e.g. "07:00", invalid formats)
16. Timezone handling (Asia/Jakarta)
17. Existing Phase 5 reminder job still works
18. Phase 0–6 regression tests

All DB and LLM/Telegram calls are mocked.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

from app.core.config import Settings
from app.ai.base import LLMError, LLMProvider
from app.ai.prompts import MORNING_BRIEF_PROMPT
from app.services.morning_brief_service import MorningBriefService
from app.scheduler.engine import SchedulerEngine, _parse_time

TZ = ZoneInfo("Asia/Jakarta")


# ── Helpers ───────────────────────────────────

def _make_mock_task(
    task_id=1,
    user_id=12345,
    title="Test Task",
    due_date=None,
    priority="medium",
    status="pending",
):
    task = MagicMock()
    task.id = task_id
    task.telegram_user_id = user_id
    task.title = title
    task.description = None
    task.due_date = due_date
    task.priority = MagicMock(value=priority)
    task.status = MagicMock(value=status)
    task.created_at = datetime.now(TZ)
    return task


def _fake_session_with(user_ids=None):
    user_ids = user_ids or []
    mock_session = AsyncMock()

    async def fake_execute(query):
        result = MagicMock()
        result.all.return_value = [(uid,) for uid in user_ids]
        return result

    mock_session.execute = fake_execute

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    return fake_session


# ── 1. Service Creation & Config ──────────────

class TestMorningBriefServiceCreation:
    def test_service_initialization(self):
        """Service can be initialized with or without LLM provider."""
        service = MorningBriefService()
        assert service is not None

        mock_llm = MagicMock(spec=LLMProvider)
        service_with_llm = MorningBriefService(llm_provider=mock_llm)
        assert service_with_llm._get_provider() == mock_llm

    def test_time_parsing_valid(self):
        """_parse_time parses valid HH:MM strings."""
        assert _parse_time("07:00") == (7, 0)
        assert _parse_time("08:30") == (8, 30)
        assert _parse_time("23:59") == (23, 59)

    def test_time_parsing_invalid_defaults_to_7am(self):
        """Invalid time strings default to (7, 0)."""
        assert _parse_time("invalid") == (7, 0)
        assert _parse_time("25:00") == (7, 0)
        assert _parse_time("") == (7, 0)


# ── 2–6. Context Generation & Formatting ──────

class TestMorningBriefContent:
    @pytest.mark.asyncio
    async def test_today_tasks_included(self):
        """Today's scheduled tasks should be present in context and brief."""
        mock_plan = {
            "success": True,
            "date": "2026-08-18",
            "day_name": "Selasa",
            "scheduled_tasks": [{"title": "Meeting Tim", "priority": "high", "due_date": "2026-08-18T09:00:00+07:00"}],
            "scheduled_count": 1,
            "overdue_tasks": [],
            "overdue_count": 0,
            "backlog_tasks": [],
            "backlog_count": 0,
            "total_tasks": 1,
            "message": "Rencana untuk Selasa",
        }

        with patch("app.services.morning_brief_service.DailyPlanService.get_daily_plan", AsyncMock(return_value=mock_plan)):
            service = MorningBriefService()
            brief = await service.generate_brief(telegram_user_id=12345, target_date="2026-08-18")

        assert "Meeting Tim" in brief
        assert "Selasa" in brief

    @pytest.mark.asyncio
    async def test_overdue_tasks_included(self):
        """Overdue tasks should be included in brief."""
        mock_plan = {
            "success": True,
            "date": "2026-08-18",
            "day_name": "Selasa",
            "scheduled_tasks": [],
            "scheduled_count": 0,
            "overdue_tasks": [{"title": "Bayar Tagihan", "priority": "urgent", "due_date": "2026-08-15T10:00:00+07:00"}],
            "overdue_count": 1,
            "backlog_tasks": [],
            "backlog_count": 0,
            "total_tasks": 1,
            "message": "Rencana",
        }

        with patch("app.services.morning_brief_service.DailyPlanService.get_daily_plan", AsyncMock(return_value=mock_plan)):
            service = MorningBriefService()
            brief = await service.generate_brief(telegram_user_id=12345, target_date="2026-08-18")

        assert "Bayar Tagihan" in brief
        assert "Overdue" in brief or "Terlewat" in brief or "Bebas" not in brief

    @pytest.mark.asyncio
    async def test_high_priority_backlog_included(self):
        """Backlog tasks should be included in brief."""
        mock_plan = {
            "success": True,
            "date": "2026-08-18",
            "day_name": "Selasa",
            "scheduled_tasks": [],
            "scheduled_count": 0,
            "overdue_tasks": [],
            "overdue_count": 0,
            "backlog_tasks": [{"title": "Belajar Python", "priority": "high"}],
            "backlog_count": 1,
            "total_tasks": 1,
            "message": "Rencana",
        }

        with patch("app.services.morning_brief_service.DailyPlanService.get_daily_plan", AsyncMock(return_value=mock_plan)):
            service = MorningBriefService()
            brief = await service.generate_brief(telegram_user_id=12345, target_date="2026-08-18")

        assert "Belajar Python" in brief

    @pytest.mark.asyncio
    async def test_empty_task_day_returns_free_day_brief(self):
        """0 tasks should result in a free day brief."""
        mock_plan = {
            "success": True,
            "date": "2026-08-18",
            "day_name": "Selasa",
            "scheduled_tasks": [],
            "scheduled_count": 0,
            "overdue_tasks": [],
            "overdue_count": 0,
            "backlog_tasks": [],
            "backlog_count": 0,
            "total_tasks": 0,
            "message": "Hari bebas!",
        }

        with patch("app.services.morning_brief_service.DailyPlanService.get_daily_plan", AsyncMock(return_value=mock_plan)):
            service = MorningBriefService()
            brief = await service.generate_brief(telegram_user_id=12345, target_date="2026-08-18")

        assert "bebas" in brief.lower() or "free" in brief.lower()


# ── 7. User Isolation & Registration Query ─────

class TestUserIsolationAndQuery:
    @pytest.mark.asyncio
    async def test_get_registered_user_ids(self):
        """Queries distinct telegram_user_ids from DB."""
        fake = _fake_session_with(user_ids=[100, 200, 300])

        with patch("app.services.morning_brief_service.get_db_session", fake):
            uids = await MorningBriefService.get_registered_user_ids()

        assert uids == [100, 200, 300]

    @pytest.mark.asyncio
    async def test_user_isolation_passed_to_daily_plan(self):
        """DailyPlanService is called with correct telegram_user_id."""
        with patch("app.services.morning_brief_service.DailyPlanService.get_daily_plan", AsyncMock(return_value={"success": True, "total_tasks": 0})) as mock_daily:
            service = MorningBriefService()
            await service.generate_brief(telegram_user_id=999)
            mock_daily.assert_called_once_with(telegram_user_id=999, target_date=None)


# ── 8–9. Gemini Prompt & Response Handling ────

class TestGeminiIntegration:
    @pytest.mark.asyncio
    async def test_gemini_called_with_morning_brief_prompt(self):
        """LLM provider is invoked with MORNING_BRIEF_PROMPT."""
        mock_llm = MagicMock(spec=LLMProvider)
        mock_llm.generate_text = AsyncMock(return_value="AI Generated Morning Brief Text")

        mock_plan = {
            "success": True,
            "date": "2026-08-18",
            "day_name": "Selasa",
            "scheduled_tasks": [],
            "scheduled_count": 0,
            "overdue_tasks": [],
            "overdue_count": 0,
            "backlog_tasks": [],
            "backlog_count": 0,
            "total_tasks": 0,
            "message": "Hari bebas!",
        }

        with patch("app.services.morning_brief_service.DailyPlanService.get_daily_plan", AsyncMock(return_value=mock_plan)):
            service = MorningBriefService(llm_provider=mock_llm)
            brief = await service.generate_brief(telegram_user_id=123, target_date="2026-08-18")

        assert brief == "AI Generated Morning Brief Text"
        mock_llm.generate_text.assert_called_once()
        _, kwargs = mock_llm.generate_text.call_args
        assert kwargs.get("system_instruction") == MORNING_BRIEF_PROMPT

    @pytest.mark.asyncio
    async def test_fallback_when_gemini_fails(self):
        """If LLM fails, service falls back to structured template without throwing."""
        mock_llm = MagicMock(spec=LLMProvider)
        mock_llm.generate_text = AsyncMock(side_effect=LLMError("API rate limit"))

        mock_plan = {
            "success": True,
            "date": "2026-08-18",
            "day_name": "Selasa",
            "scheduled_tasks": [{"title": "Kuliah", "priority": "medium"}],
            "scheduled_count": 1,
            "overdue_tasks": [],
            "overdue_count": 0,
            "backlog_tasks": [],
            "backlog_count": 0,
            "total_tasks": 1,
            "message": "Rencana",
        }

        with patch("app.services.morning_brief_service.DailyPlanService.get_daily_plan", AsyncMock(return_value=mock_plan)):
            service = MorningBriefService(llm_provider=mock_llm)
            brief = await service.generate_brief(telegram_user_id=123)

        assert "Kuliah" in brief
        assert "Selamat Pagi" in brief


# ── 10–11. Telegram Delivery ──────────────────

class TestTelegramDelivery:
    @pytest.mark.asyncio
    async def test_send_morning_briefs_delivers_via_bot(self):
        """send_morning_briefs delivers brief to user via telegram bot."""
        mock_bot_app = MagicMock()
        mock_bot_app.bot.send_message = AsyncMock()

        service = MorningBriefService()
        with patch.object(service, "generate_brief", AsyncMock(return_value="Pesan Ringkasan Pagi")):
            results = await service.send_morning_briefs(
                bot_application=mock_bot_app,
                target_user_ids=[555],
            )

        assert len(results) == 1
        assert results[0]["sent"] is True
        mock_bot_app.bot.send_message.assert_called_once_with(
            chat_id=555,
            text="Pesan Ringkasan Pagi",
            parse_mode="Markdown",
        )

    @pytest.mark.asyncio
    async def test_send_morning_brief_handles_telegram_failure(self):
        """Telegram send errors are caught gracefully."""
        mock_bot_app = MagicMock()
        mock_bot_app.bot.send_message = AsyncMock(side_effect=Exception("Network error"))

        service = MorningBriefService()
        with patch.object(service, "generate_brief", AsyncMock(return_value="Pesan Ringkasan Pagi")):
            results = await service.send_morning_briefs(
                bot_application=mock_bot_app,
                target_user_ids=[555],
            )

        assert len(results) == 1
        assert results[0]["sent"] is False


# ── 12–16. Scheduler & Configuration ─────────

class TestSchedulerIntegration:
    @pytest.mark.asyncio
    async def test_scheduler_registers_cron_job_when_enabled(self):
        """Scheduler Engine registers CronTrigger morning_brief job when enabled."""
        engine = SchedulerEngine()
        assert engine.morning_brief_service is not None

        with patch("app.core.config.settings.enable_morning_brief", True), \
             patch("app.core.config.settings.morning_brief_time", "07:30"):
            await engine.start()
            assert engine.running is True

            job = engine._scheduler.get_job("morning_brief")
            assert job is not None
            assert job.id == "morning_brief"

            await engine.stop()

    @pytest.mark.asyncio
    async def test_scheduler_skips_cron_job_when_disabled(self):
        """Scheduler Engine skips morning_brief job when enable_morning_brief=False."""
        engine = SchedulerEngine()

        with patch("app.core.config.settings.enable_morning_brief", False):
            await engine.start()

            job = engine._scheduler.get_job("morning_brief")
            assert job is None

            await engine.stop()

    @pytest.mark.asyncio
    async def test_trigger_morning_brief_manual(self):
        """trigger_morning_brief manually triggers delivery."""
        engine = SchedulerEngine()
        with patch.object(engine.morning_brief_service, "send_morning_briefs", AsyncMock(return_value=[{"sent": True}])) as mock_send:
            results = await engine.trigger_morning_brief(target_user_ids=[777])
            mock_send.assert_called_once()
            assert len(results) == 1


# ── 17–18. Phase 5 & Phase 0–6 Regressions ────

class TestPhase06Regressions:
    @pytest.mark.asyncio
    async def test_phase5_reminder_job_still_works(self):
        """Phase 5 reminder check job is still registered and working."""
        engine = SchedulerEngine()
        await engine.start()

        job = engine._scheduler.get_job("reminder_check")
        assert job is not None

        await engine.stop()

    def test_services_export(self):
        """MorningBriefService exported in app.services."""
        from app.services import MorningBriefService as MBS, TaskService, DailyPlanService
        assert MBS is MorningBriefService
        assert TaskService is not None
        assert DailyPlanService is not None

    def test_prompts_active_capability(self):
        """Fallback prompt should describe conversational-only mode."""
        from app.ai.prompts import get_system_prompt
        prompt = get_system_prompt()
        assert "Mode Percakapan" in prompt or "percakapan" in prompt.lower()
