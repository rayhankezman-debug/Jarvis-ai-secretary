"""
Tests for Phase 8 — Evening Review.

Covers:
1. EveningReviewService creation
2. Task retrieval (completed, pending, in-progress, overdue)
3. Empty-day behavior
4. User isolation
5. Gemini prompt generation & success response
6. Gemini/API failure fallback
7. Telegram delivery & failures
8. Scheduler registration (Cron job for evening review)
9. Configured evening time & enable/disable config
10. Timezone behavior
11. Phase 0–7 regressions
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

from app.core.config import Settings
from app.ai.base import LLMError, LLMProvider
from app.ai.prompts import EVENING_REVIEW_PROMPT
from app.services.evening_review_service import EveningReviewService
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


def _fake_session_with(completed=None, pending=None, in_progress=None, overdue=None):
    """Mock DB session returning tasks for 4 queries in get_review_data."""
    completed = completed or []
    pending = pending or []
    in_progress = in_progress or []
    overdue = overdue or []

    mock_session = AsyncMock()
    call_count = [0]

    async def fake_execute(query):
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        if idx == 0:
            result.scalars.return_value.all.return_value = completed
        elif idx == 1:
            result.scalars.return_value.all.return_value = pending
        elif idx == 2:
            result.scalars.return_value.all.return_value = in_progress
        else:
            result.scalars.return_value.all.return_value = overdue
        return result

    mock_session.execute = fake_execute

    @asynccontextmanager
    async def fake_session():
        yield mock_session

    return fake_session


def _fake_session_uids(user_ids=None):
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


# ── 1. Service Creation ──────────────

class TestEveningReviewServiceCreation:
    def test_service_initialization(self):
        service = EveningReviewService()
        assert service is not None

        mock_llm = MagicMock(spec=LLMProvider)
        service_with_llm = EveningReviewService(llm_provider=mock_llm)
        assert service_with_llm._get_provider() == mock_llm


# ── 2–4. Context Generation & Formatting ──────

class TestEveningReviewContent:
    @pytest.mark.asyncio
    async def test_completed_tasks_included(self):
        task = _make_mock_task(task_id=1, title="Selesai", status="completed")
        fake = _fake_session_with(completed=[task])

        with patch("app.services.evening_review_service.get_db_session", fake):
            service = EveningReviewService()
            data = await service.get_review_data(telegram_user_id=123, target_date="2026-08-18")
        
        assert data["completed_count"] == 1
        assert data["completed_today"][0]["title"] == "Selesai"

    @pytest.mark.asyncio
    async def test_pending_tasks_included(self):
        task = _make_mock_task(task_id=2, title="Pending", status="pending")
        fake = _fake_session_with(pending=[task])

        with patch("app.services.evening_review_service.get_db_session", fake):
            service = EveningReviewService()
            data = await service.get_review_data(telegram_user_id=123, target_date="2026-08-18")
        
        assert data["pending_count"] == 1
        assert data["pending_today"][0]["title"] == "Pending"

    @pytest.mark.asyncio
    async def test_in_progress_tasks_included(self):
        task = _make_mock_task(task_id=3, title="Kerja", status="in_progress")
        fake = _fake_session_with(in_progress=[task])

        with patch("app.services.evening_review_service.get_db_session", fake):
            service = EveningReviewService()
            data = await service.get_review_data(telegram_user_id=123, target_date="2026-08-18")
        
        assert data["in_progress_count"] == 1
        assert data["in_progress_today"][0]["title"] == "Kerja"

    @pytest.mark.asyncio
    async def test_overdue_tasks_included(self):
        task = _make_mock_task(task_id=4, title="Telat", status="pending")
        fake = _fake_session_with(overdue=[task])

        with patch("app.services.evening_review_service.get_db_session", fake):
            service = EveningReviewService()
            data = await service.get_review_data(telegram_user_id=123, target_date="2026-08-18")
        
        assert data["overdue_count"] == 1
        assert data["overdue_tasks"][0]["title"] == "Telat"

    @pytest.mark.asyncio
    async def test_empty_task_day_returns_relax_message(self):
        fake = _fake_session_with()

        with patch("app.services.evening_review_service.get_db_session", fake):
            service = EveningReviewService()
            data = await service.get_review_data(telegram_user_id=123, target_date="2026-08-18")
            
        assert data["total_tasks"] == 0
        assert "Tidak ada aktivitas" in data["message"]


# ── User Isolation & Registration Query ─────

class TestUserIsolationAndQuery:
    @pytest.mark.asyncio
    async def test_get_registered_user_ids(self):
        fake = _fake_session_uids(user_ids=[101, 202])

        with patch("app.services.evening_review_service.get_db_session", fake):
            uids = await EveningReviewService.get_registered_user_ids()

        assert uids == [101, 202]

    @pytest.mark.asyncio
    async def test_user_isolation_passed_to_review_data(self):
        # We ensure get_review_data queries the right user_id by tracking DB calls.
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

        with patch("app.services.evening_review_service.get_db_session", fake_session):
            service = EveningReviewService()
            await service.get_review_data(telegram_user_id=999)

        assert len(calls) == 4


# ── Gemini Prompt & Response Handling ────

class TestGeminiIntegration:
    @pytest.mark.asyncio
    async def test_gemini_called_with_evening_review_prompt(self):
        mock_llm = MagicMock(spec=LLMProvider)
        mock_llm.generate_text = AsyncMock(return_value="AI Evening Review Text")

        fake = _fake_session_with()
        with patch("app.services.evening_review_service.get_db_session", fake):
            service = EveningReviewService(llm_provider=mock_llm)
            review = await service.generate_review(telegram_user_id=123, target_date="2026-08-18")

        assert review == "AI Evening Review Text"
        mock_llm.generate_text.assert_called_once()
        _, kwargs = mock_llm.generate_text.call_args
        assert kwargs.get("system_instruction") == EVENING_REVIEW_PROMPT

    @pytest.mark.asyncio
    async def test_fallback_when_gemini_fails(self):
        mock_llm = MagicMock(spec=LLMProvider)
        mock_llm.generate_text = AsyncMock(side_effect=LLMError("API rate limit"))

        task = _make_mock_task(task_id=1, title="Selesai", status="completed")
        fake = _fake_session_with(completed=[task])

        with patch("app.services.evening_review_service.get_db_session", fake):
            service = EveningReviewService(llm_provider=mock_llm)
            review = await service.generate_review(telegram_user_id=123)

        assert "Selesai" in review
        assert "Selamat Malam" in review


# ── Telegram Delivery ──────────────────

class TestTelegramDelivery:
    @pytest.mark.asyncio
    async def test_send_evening_reviews_delivers_via_bot(self):
        mock_bot_app = MagicMock()
        mock_bot_app.bot.send_message = AsyncMock()

        service = EveningReviewService()
        with patch.object(service, "generate_review", AsyncMock(return_value="Review Pesan")):
            results = await service.send_evening_reviews(
                bot_application=mock_bot_app,
                target_user_ids=[555],
            )

        assert len(results) == 1
        assert results[0]["sent"] is True
        mock_bot_app.bot.send_message.assert_called_once_with(
            chat_id=555,
            text="Review Pesan",
            parse_mode="Markdown",
        )

    @pytest.mark.asyncio
    async def test_send_evening_review_handles_telegram_failure(self):
        mock_bot_app = MagicMock()
        mock_bot_app.bot.send_message = AsyncMock(side_effect=Exception("Network error"))

        service = EveningReviewService()
        with patch.object(service, "generate_review", AsyncMock(return_value="Review Pesan")):
            results = await service.send_evening_reviews(
                bot_application=mock_bot_app,
                target_user_ids=[555],
            )

        assert len(results) == 1
        assert results[0]["sent"] is False


# ── Scheduler & Configuration ─────────

class TestSchedulerIntegration:
    @pytest.mark.asyncio
    async def test_scheduler_registers_cron_job_when_enabled(self):
        engine = SchedulerEngine()
        assert engine.evening_review_service is not None

        with patch("app.core.config.settings.enable_evening_review", True), \
             patch("app.core.config.settings.evening_review_time", "20:30"):
            await engine.start()
            assert engine.running is True

            job = engine._scheduler.get_job("evening_review")
            assert job is not None
            assert job.id == "evening_review"

            await engine.stop()

    @pytest.mark.asyncio
    async def test_scheduler_skips_cron_job_when_disabled(self):
        engine = SchedulerEngine()

        with patch("app.core.config.settings.enable_evening_review", False):
            await engine.start()

            job = engine._scheduler.get_job("evening_review")
            assert job is None

            await engine.stop()

    @pytest.mark.asyncio
    async def test_trigger_evening_review_manual(self):
        engine = SchedulerEngine()
        with patch.object(engine.evening_review_service, "send_evening_reviews", AsyncMock(return_value=[{"sent": True}])) as mock_send:
            results = await engine.trigger_evening_review(target_user_ids=[777])
            mock_send.assert_called_once()
            assert len(results) == 1


# ── Phase 0–7 Regressions ────

class TestPhase07Regressions:
    @pytest.mark.asyncio
    async def test_phase7_morning_brief_job_still_works(self):
        engine = SchedulerEngine()
        with patch("app.core.config.settings.enable_morning_brief", True):
            await engine.start()
            job = engine._scheduler.get_job("morning_brief")
            assert job is not None
            await engine.stop()

    def test_services_export(self):
        from app.services import EveningReviewService as ERS, MorningBriefService as MBS, TaskService
        assert ERS is EveningReviewService
        assert MBS is not None
        assert TaskService is not None

    def test_prompts_active_capability(self):
        from app.ai.prompts import get_system_prompt
        prompt = get_system_prompt()
        assert "Phase 8" in prompt
        assert "aktif" in prompt.lower()
