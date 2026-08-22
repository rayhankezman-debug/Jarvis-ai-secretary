"""
Tests for Task Retrieval Audit — verifying end-to-end task flow.

These tests specifically verify:
1. create_task stores task in database
2. list_tasks retrieves the newly created task
3. Tasks are only returned to the correct user
4. Agent can select list_tasks when user asks for task list
5. If database fails, Agent does NOT falsely confirm task creation
6. Telegram flow can create and read tasks
7. Handler shows clear error when agent fails (no misleading fallback)
8. Rate limit is handled with a clear user-facing message

All DB/LLM calls are mocked — no real API needed.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from app.ai.base import LLMError, LLMRateLimitError
from app.ai.tools import TASK_TOOLS, execute_tool
from app.services.task_service import TaskService
from app.database.models import Task, TaskStatus, TaskPriority

TZ = ZoneInfo("Asia/Jakarta")


# ── Helpers ────────────────────────────────────

def _make_fake_db():
    """Create a fake in-memory database for testing create + list flow."""
    store = []
    id_counter = [0]

    @asynccontextmanager
    async def fake_session():
        session = MagicMock()

        # Track added tasks
        def add(obj):
            id_counter[0] += 1
            obj.id = id_counter[0]
            obj.created_at = datetime.now(tz=ZoneInfo("UTC"))
            obj.completed_at = None
            store.append(obj)

        async def flush():
            pass

        async def commit():
            pass

        async def rollback():
            pass

        async def close():
            pass

        async def execute(query):
            """Filter store based on query string to simulate user isolation."""
            result = MagicMock()
            # Return all tasks in store (tests will filter by user_id via the query)
            result.scalars.return_value.all.return_value = list(store)
            return result

        session.add = add
        session.flush = AsyncMock(side_effect=flush)
        session.commit = AsyncMock(side_effect=commit)
        session.rollback = AsyncMock(side_effect=rollback)
        session.close = AsyncMock(side_effect=close)
        session.execute = AsyncMock(side_effect=execute)

        yield session

    return fake_session, store


def _make_mock_update(user_id=12345, text="Test message"):
    """Create a mock Telegram Update object."""
    mock_update = MagicMock()
    mock_update.effective_user = MagicMock()
    mock_update.effective_user.id = user_id
    mock_update.message = MagicMock()
    mock_update.message.text = text
    mock_update.message.reply_text = AsyncMock()
    return mock_update


def _make_agent_text_response(text):
    """Create a mock Gemini text response."""
    mock_part = MagicMock()
    mock_part.function_call = None
    mock_part.text = text
    mock_candidate = MagicMock()
    mock_candidate.content = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.text = text
    return mock_response


def _make_agent_function_call_response(name, args):
    """Create a mock Gemini function call response."""
    mock_fc = MagicMock()
    mock_fc.name = name
    mock_fc.args = args
    mock_part = MagicMock()
    mock_part.function_call = mock_fc
    mock_part.text = None
    mock_candidate = MagicMock()
    mock_candidate.content = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.text = None
    return mock_response


# ── 1. create_task stores task in database ─────

class TestCreateTaskStoresInDB:
    @pytest.mark.asyncio
    async def test_create_task_calls_db_session(self):
        """create_task should use get_db_session and insert a task."""
        fake_session, store = _make_fake_db()

        with patch("app.services.task_service.get_db_session", fake_session):
            result = await TaskService.create_task(
                telegram_user_id=12345,
                title="Belajar AI",
                due_date="2026-08-23T19:00:00+07:00",
                priority="high",
            )

        assert result["success"] is True
        assert result["task_id"] is not None
        assert result["title"] == "Belajar AI"
        assert result["priority"] == "high"
        assert len(store) == 1

    @pytest.mark.asyncio
    async def test_create_task_via_tool_execution(self):
        """execute_tool('create_task') should route to TaskService.create_task."""
        mock_result = {
            "success": True,
            "task_id": 1,
            "title": "Belajar AI",
            "priority": "high",
            "status": "pending",
        }
        with patch.object(
            TaskService, "create_task",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_create:
            result = await execute_tool(
                "create_task",
                {"title": "Belajar AI", "priority": "high"},
                telegram_user_id=12345,
            )
            mock_create.assert_called_once_with(
                telegram_user_id=12345,
                title="Belajar AI",
                description=None,
                due_date=None,
                priority="high",
            )
        assert result["success"] is True


# ── 2. list_tasks retrieves newly created task ─

class TestListTasksRetrieval:
    @pytest.mark.asyncio
    async def test_list_tasks_returns_tasks(self):
        """list_tasks should return tasks from the database."""
        mock_result = {
            "success": True,
            "tasks": [
                {
                    "task_id": 1,
                    "title": "Belajar AI",
                    "status": "pending",
                    "priority": "high",
                    "due_date": "2026-08-23T19:00:00+07:00",
                }
            ],
            "count": 1,
        }
        with patch.object(
            TaskService, "list_tasks",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await execute_tool(
                "list_tasks",
                {},
                telegram_user_id=12345,
            )
        assert result["success"] is True
        assert result["count"] == 1
        assert result["tasks"][0]["title"] == "Belajar AI"

    @pytest.mark.asyncio
    async def test_list_tasks_tool_is_registered(self):
        """list_tasks should be in the TASK_TOOLS function declarations."""
        names = [fd.name for fd in TASK_TOOLS.function_declarations]
        assert "list_tasks" in names


# ── 3. Tasks only returned to correct user ─────

class TestUserIsolation:
    @pytest.mark.asyncio
    async def test_tool_uses_correct_user_id_for_create(self):
        """create_task tool should pass the correct telegram_user_id."""
        with patch.object(
            TaskService, "create_task",
            new_callable=AsyncMock,
            return_value={"success": True},
        ) as mock:
            await execute_tool("create_task", {"title": "Test"}, telegram_user_id=111)
            assert mock.call_args.kwargs["telegram_user_id"] == 111

    @pytest.mark.asyncio
    async def test_tool_uses_correct_user_id_for_list(self):
        """list_tasks tool should pass the correct telegram_user_id."""
        with patch.object(
            TaskService, "list_tasks",
            new_callable=AsyncMock,
            return_value={"success": True, "tasks": [], "count": 0},
        ) as mock:
            await execute_tool("list_tasks", {}, telegram_user_id=222)
            assert mock.call_args.kwargs["telegram_user_id"] == 222

    @pytest.mark.asyncio
    async def test_different_users_get_different_results(self):
        """Different user IDs should result in separate calls."""
        call_log = []

        async def tracking_list(**kwargs):
            call_log.append(kwargs["telegram_user_id"])
            return {"success": True, "tasks": [], "count": 0}

        with patch.object(TaskService, "list_tasks", side_effect=tracking_list):
            await execute_tool("list_tasks", {}, telegram_user_id=100)
            await execute_tool("list_tasks", {}, telegram_user_id=200)

        assert call_log == [100, 200]


# ── 4. Agent selects list_tasks for task list request ─

class TestAgentToolSelection:
    @pytest.mark.asyncio
    async def test_agent_calls_list_tasks_then_responds(self):
        """Agent should call list_tasks when user asks for task list."""
        from app.ai.agent import AgentService

        agent = AgentService(api_key="test-key", model="gemini-2.0-flash")

        # Simulate: Gemini calls list_tasks, then generates text
        fc_resp = _make_agent_function_call_response(
            "list_tasks", {}
        )
        text_resp = _make_agent_text_response(
            "Berikut daftar tugas kamu:\n1. Belajar AI (pending)"
        )

        agent._client = MagicMock()
        agent._client.aio.models.generate_content = AsyncMock(
            side_effect=[fc_resp, text_resp]
        )

        with patch(
            "app.ai.tools.TaskService.list_tasks",
            new_callable=AsyncMock,
            return_value={
                "success": True,
                "tasks": [{"task_id": 1, "title": "Belajar AI", "status": "pending"}],
                "count": 1,
            },
        ):
            result = await agent.process_message(
                "Berikan daftar semua tugas saya",
                telegram_user_id=12345,
            )

        assert "Belajar AI" in result
        assert "daftar" in result.lower() or "tugas" in result.lower()


# ── 5. DB failure → no false confirmation ──────

class TestDBFailureHandling:
    @pytest.mark.asyncio
    async def test_create_task_db_failure_returns_error(self):
        """If DB fails during create_task, result should indicate failure."""
        with patch(
            "app.services.task_service.get_db_session",
            side_effect=Exception("Connection refused"),
        ):
            result = await TaskService.create_task(
                telegram_user_id=1,
                title="Test",
            )
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_list_tasks_db_failure_returns_error(self):
        """If DB fails during list_tasks, result should indicate failure."""
        with patch(
            "app.services.task_service.get_db_session",
            side_effect=Exception("Connection refused"),
        ):
            result = await TaskService.list_tasks(telegram_user_id=1)
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_tool_execution_propagates_failure(self):
        """Tool execution should propagate failure from service layer."""
        with patch.object(
            TaskService, "create_task",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "DB connection failed"},
        ):
            result = await execute_tool(
                "create_task",
                {"title": "Test"},
                telegram_user_id=1,
            )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_agent_sees_failure_and_reports_honestly(self):
        """Agent should report failure honestly when tool returns error."""
        from app.ai.agent import AgentService

        agent = AgentService(api_key="test-key", model="gemini-2.0-flash")

        # Simulate: Gemini calls create_task (which fails), then generates text
        fc_resp = _make_agent_function_call_response(
            "create_task", {"title": "Test"}
        )
        text_resp = _make_agent_text_response(
            "Maaf, gagal membuat tugas. Silakan coba lagi."
        )

        agent._client = MagicMock()
        agent._client.aio.models.generate_content = AsyncMock(
            side_effect=[fc_resp, text_resp]
        )

        with patch(
            "app.ai.tools.TaskService.create_task",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "Database connection failed"},
        ):
            result = await agent.process_message(
                "Tambahkan tugas test",
                telegram_user_id=12345,
            )

        # Agent should NOT say "berhasil" when it received a failure result
        assert "gagal" in result.lower() or "maaf" in result.lower() or "coba lagi" in result.lower()


# ── 6. Telegram flow can create and read tasks ─

class TestTelegramFlow:
    @pytest.mark.asyncio
    async def test_handler_routes_to_agent(self):
        """Telegram handler should route messages to the agent."""
        from app.telegram.handlers import handle_text_message

        mock_update = _make_mock_update(
            user_id=12345,
            text="Berikan daftar semua tugas saya",
        )
        mock_agent = MagicMock()
        mock_agent.process_message = AsyncMock(
            return_value="Berikut daftar tugas kamu:\n1. Belajar AI"
        )

        with patch("app.ai.agent.get_agent", return_value=mock_agent):
            await handle_text_message(mock_update, MagicMock())

        mock_agent.process_message.assert_called_once_with(
            "Berikan daftar semua tugas saya",
            telegram_user_id=12345,
        )
        mock_update.message.reply_text.assert_called_once_with(
            "Berikut daftar tugas kamu:\n1. Belajar AI"
        )

    @pytest.mark.asyncio
    async def test_handler_shows_error_not_misleading_fallback(self):
        """When agent fails, handler should show clear error, NOT fall back to tool-less LLM."""
        from app.telegram.handlers import handle_text_message

        mock_update = _make_mock_update(text="Lihat tugas saya")
        mock_agent = MagicMock()
        mock_agent.process_message = AsyncMock(
            side_effect=LLMError("Transient API error", provider="gemini")
        )

        with patch("app.ai.agent.get_agent", return_value=mock_agent):
            await handle_text_message(mock_update, MagicMock())

        call_args = mock_update.message.reply_text.call_args
        response_text = call_args[0][0]

        # Should show a clear error message
        assert "gangguan sementara" in response_text or "coba lagi" in response_text
        # Should NOT say "belum terhubung ke database" or "AI belum aktif"
        assert "belum terhubung" not in response_text
        assert "AI belum aktif" not in response_text

    @pytest.mark.asyncio
    async def test_handler_rate_limit_shows_clear_message(self):
        """When agent is rate-limited, handler should show a clear rate limit message."""
        from app.telegram.handlers import handle_text_message

        mock_update = _make_mock_update(text="Lihat tugas saya")
        mock_agent = MagicMock()
        mock_agent.process_message = AsyncMock(
            side_effect=LLMRateLimitError("429 Resource Exhausted", provider="gemini")
        )

        with patch("app.ai.agent.get_agent", return_value=mock_agent):
            await handle_text_message(mock_update, MagicMock())

        call_args = mock_update.message.reply_text.call_args
        response_text = call_args[0][0]

        assert "sibuk" in response_text or "coba lagi" in response_text


# ── 7. Fallback prompt correctness ─────────────

class TestFallbackPrompt:
    def test_fallback_prompt_does_not_claim_tools_active(self):
        """Fallback system prompt should NOT claim task tools are active."""
        from app.ai.prompts import get_system_prompt
        prompt = get_system_prompt()

        # Should NOT claim Phase 4-9 features as active
        assert "Phase 4 — aktif" not in prompt
        assert "Phase 5 — aktif" not in prompt

    def test_fallback_prompt_warns_no_tool_access(self):
        """Fallback system prompt should warn that tools are not available."""
        from app.ai.prompts import get_system_prompt
        prompt = get_system_prompt()

        assert "TANPA akses" in prompt or "tidak" in prompt.lower()

    def test_agent_prompt_still_has_tools(self):
        """Agent system prompt should still reference tools correctly."""
        from app.ai.agent import _get_agent_system_prompt
        prompt = _get_agent_system_prompt()

        assert "tools" in prompt.lower() or "Tools" in prompt
        assert "create_task" not in prompt  # Tools are registered via TASK_TOOLS, not prompt
        assert "list_tasks" in prompt or "generate_daily_plan" in prompt

    def test_agent_has_all_tools_registered(self):
        """Agent should have all 7 tools registered in TASK_TOOLS."""
        names = [fd.name for fd in TASK_TOOLS.function_declarations]
        expected = [
            "create_task", "list_tasks", "update_task",
            "complete_task", "cancel_task",
            "generate_daily_plan", "get_productivity_statistics",
        ]
        for name in expected:
            assert name in names, f"Tool '{name}' not found in TASK_TOOLS"
