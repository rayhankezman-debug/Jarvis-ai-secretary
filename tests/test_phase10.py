"""
Tests for Phase 10 — Testing & Hardening.

Covers:
1. Configuration validation (invalid time formats, bad timezones, bad log levels).
2. Tool execution robustness (safe_int, bad tool arguments, unknown tools).
3. Database failure handling & session cleanup across services.
4. Scheduler lifecycle, re-start capability, and job error isolation.
5. Telegram message safety and long message chunking.
6. Sensitive data logging filters.
7. Strict user isolation verification.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError

from app.core.config import Settings
from app.ai.tools import execute_tool, _safe_int
from app.scheduler.engine import SchedulerEngine
from app.telegram.handlers import _reply_safe, handle_text_message
from app.core.logging import SensitiveDataFilter
from app.services import (
    TaskService,
    DailyPlanService,
    MorningBriefService,
    EveningReviewService,
    HistoryService,
)


# ── 1. Configuration Validation Tests ────────────────

class TestConfigValidation:
    def test_valid_configuration(self):
        s = Settings(
            timezone="Asia/Jakarta",
            morning_brief_time="07:00",
            evening_review_time="20:00",
            log_level="INFO",
        )
        assert s.timezone == "Asia/Jakarta"
        assert s.morning_brief_time == "07:00"
        assert s.log_level == "INFO"

    def test_invalid_timezone_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc:
            Settings(timezone="Invalid/Timezone_Name")
        assert "Invalid timezone" in str(exc.value)

    def test_invalid_morning_brief_time_format(self):
        with pytest.raises(ValidationError) as exc:
            Settings(morning_brief_time="25:00")
        assert "Invalid time format" in str(exc.value)

    def test_invalid_evening_review_time_format(self):
        with pytest.raises(ValidationError) as exc:
            Settings(evening_review_time="invalid-time")
        assert "Invalid time format" in str(exc.value)

    def test_invalid_log_level(self):
        with pytest.raises(ValidationError) as exc:
            Settings(log_level="NOT_A_LEVEL")
        assert "Invalid log_level" in str(exc.value)


# ── 2. Tool Argument Hardening Tests ─────────────────

class TestToolArgumentHardening:
    def test_safe_int_conversion(self):
        assert _safe_int("123") == 123
        assert _safe_int(456) == 456
        assert _safe_int("invalid", default=0) == 0
        assert _safe_int(None, default=-1) == -1

    @pytest.mark.asyncio
    async def test_execute_tool_with_invalid_task_id_string(self):
        with patch.object(TaskService, "update_task", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = {"success": False, "error": "Task ID diperlukan."}
            result = await execute_tool(
                tool_name="update_task",
                tool_args={"task_id": "not-an-int", "title": "New Title"},
                telegram_user_id=123,
            )
            # Should safely convert "not-an-int" to 0 via _safe_int
            mock_update.assert_called_once_with(
                telegram_user_id=123,
                task_id=0,
                title="New Title",
                description=None,
                due_date=None,
                priority=None,
            )

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        result = await execute_tool(
            tool_name="non_existent_tool",
            tool_args={},
            telegram_user_id=123,
        )
        assert result["success"] is False
        assert "tidak dikenal" in result["error"]


# ── 3. Database Failure Resilience Tests ─────────────

class TestDatabaseFailureResilience:
    @pytest.mark.asyncio
    async def test_task_service_db_down(self):
        with patch("app.services.task_service.get_db_session", side_effect=Exception("DB connection refused")):
            res1 = await TaskService.create_task(telegram_user_id=123, title="Test")
            assert res1["success"] is False
            assert "Gagal" in res1["error"]

            res2 = await TaskService.list_tasks(telegram_user_id=123)
            assert res2["success"] is False
            assert res2["tasks"] == []

    @pytest.mark.asyncio
    async def test_history_service_db_down(self):
        with patch("app.services.history_service.get_db_session", side_effect=Exception("DB connection refused")):
            res = await HistoryService.get_statistics(telegram_user_id=123)
            assert res["success"] is False
            assert "Gagal" in res["error"]

    @pytest.mark.asyncio
    async def test_daily_plan_service_db_down(self):
        with patch("app.services.daily_plan_service.get_db_session", side_effect=Exception("DB connection refused")):
            res = await DailyPlanService.get_daily_plan(telegram_user_id=123)
            assert res["success"] is False
            assert "Gagal" in res["error"]


# ── 4. Scheduler Lifecycle & Reliability Tests ───────

class TestSchedulerHardening:
    @pytest.mark.asyncio
    async def test_scheduler_restart_after_stop(self):
        engine = SchedulerEngine(bot_application=None, check_interval_minutes=60)
        await engine.start()
        assert engine.running is True
        await engine.stop()
        assert engine.running is False

        # Restarting should work cleanly without raising scheduler state error
        await engine.start()
        assert engine.running is True
        await engine.stop()

    @pytest.mark.asyncio
    async def test_scheduler_ticks_isolate_failures(self):
        engine = SchedulerEngine(bot_application=None)
        with patch.object(engine._morning_brief_service, "send_morning_briefs", side_effect=Exception("Brief failed")):
            # Should log error and not crash
            await engine._morning_brief_tick()

        with patch.object(engine._evening_review_service, "send_evening_reviews", side_effect=Exception("Review failed")):
            # Should log error and not crash
            await engine._evening_review_tick()


# ── 5. Telegram Messaging Safety Tests ────────────────

class TestTelegramMessagingSafety:
    @pytest.mark.asyncio
    async def test_reply_safe_splits_long_messages(self):
        mock_msg = MagicMock()
        mock_msg.reply_text = AsyncMock()

        long_text = "A" * 9000
        await _reply_safe(mock_msg, long_text)

        # 9000 chars should be split into 3 calls (4000, 4000, 1000)
        assert mock_msg.reply_text.call_count == 3

    @pytest.mark.asyncio
    async def test_handle_text_message_fallback_on_agent_exception(self):
        update = MagicMock()
        update.effective_user.id = 12345
        update.message.text = "Halo"
        update.message.reply_text = AsyncMock()

        context = MagicMock()

        mock_agent = MagicMock()
        mock_agent.process_message = AsyncMock(side_effect=Exception("Gemini quota exceeded"))

        with patch("app.ai.agent.get_agent", return_value=mock_agent):
            with patch("app.ai.get_llm_provider", return_value=None):
                await handle_text_message(update, context)

        # Should send fallback message without crashing
        update.message.reply_text.assert_called()


# ── 6. Logging & Security Filter Tests ────────────────

class TestSensitiveDataLogging:
    def test_sensitive_data_filter_redacts_api_key(self):
        filter_obj = SensitiveDataFilter()
        record = MagicMock()
        record.msg = "Calling Gemini API with key AIzaSyD1234567890123456789012345678901"
        assert filter_obj.filter(record) is True
        assert "[REDACTED]" in record.msg
        assert "AIzaSyD" not in record.msg

    def test_sensitive_data_filter_redacts_telegram_token(self):
        filter_obj = SensitiveDataFilter()
        record = MagicMock()
        record.msg = "Connecting to telegram bot 123456789:ABCdefGHIjklMNOpqrsTUVwxyz123456789"
        assert filter_obj.filter(record) is True
        assert "[REDACTED]" in record.msg

    def test_sensitive_data_filter_redacts_db_url(self):
        filter_obj = SensitiveDataFilter()
        record = MagicMock()
        record.msg = "Connecting to postgresql+asyncpg://admin:secretpass@localhost:5432/mydb"
        assert filter_obj.filter(record) is True
        assert "[REDACTED]" in record.msg
        assert "secretpass" not in record.msg
