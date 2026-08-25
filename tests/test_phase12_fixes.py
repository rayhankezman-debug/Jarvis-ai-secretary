"""
Tests for Phase 12 — Database Migration & Gemini Thought Signature Fixes.

Covers:
1. Alembic migration file exists and creates the 'tasks' table.
2. Migration includes all required columns, indexes, and enums.
3. Agent preserves thought_signature in conversation history.
4. Agent does not reconstruct Content/Part objects (which would strip thought_signature).
5. google-genai SDK version supports thought_signature.
6. Regression tests to ensure existing agent behavior is unchanged.

All Gemini API calls are mocked — no real API needed.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from pathlib import Path
from zoneinfo import ZoneInfo

from app.ai.base import LLMError, LLMRateLimitError


# ── 1. Alembic Migration Tests ────────────────


class TestAlembicMigration:
    def test_versions_directory_has_migration_files(self):
        """alembic/versions/ should contain at least one migration file."""
        versions_dir = Path(__file__).parent.parent / "alembic" / "versions"
        py_files = list(versions_dir.glob("*.py"))
        assert len(py_files) >= 1, "No migration files found in alembic/versions/"

    def test_initial_migration_creates_tasks_table(self):
        """The initial migration should create the 'tasks' table."""
        versions_dir = Path(__file__).parent.parent / "alembic" / "versions"
        migration_files = list(versions_dir.glob("*_initial_tables.py"))
        assert len(migration_files) == 1, "Expected exactly one initial_tables migration"

        content = migration_files[0].read_text()
        assert "op.create_table('tasks'" in content
        assert "telegram_user_id" in content
        assert "title" in content
        assert "status" in content
        assert "priority" in content
        assert "due_date" in content
        assert "completed_at" in content
        assert "created_at" in content
        assert "updated_at" in content

    def test_migration_has_indexes(self):
        """The migration should create indexes on status and telegram_user_id."""
        versions_dir = Path(__file__).parent.parent / "alembic" / "versions"
        migration_files = list(versions_dir.glob("*_initial_tables.py"))
        content = migration_files[0].read_text()
        assert "ix_tasks_status" in content
        assert "ix_tasks_telegram_user_id" in content

    def test_migration_has_downgrade(self):
        """The migration should have a downgrade function that drops the table."""
        versions_dir = Path(__file__).parent.parent / "alembic" / "versions"
        migration_files = list(versions_dir.glob("*_initial_tables.py"))
        content = migration_files[0].read_text()
        assert "def downgrade()" in content
        assert "op.drop_table('tasks')" in content

    def test_migration_uses_correct_enum_names(self):
        """The migration should use non-native enums for status and priority."""
        versions_dir = Path(__file__).parent.parent / "alembic" / "versions"
        migration_files = list(versions_dir.glob("*_initial_tables.py"))
        content = migration_files[0].read_text()
        assert "task_status" in content
        assert "task_priority" in content
        assert "native_enum=False" in content


# ── 2. SDK Version Tests ──────────────────────


class TestSDKVersion:
    def test_genai_sdk_supports_thought_signature(self):
        """The installed google-genai SDK should have thought_signature on Part."""
        from google.genai import types
        part = types.Part(text="test")
        assert hasattr(part, "thought_signature"), \
            "google-genai SDK does not support thought_signature — update to >= 1.50.0"

    def test_genai_sdk_preserves_thought_signature_in_content(self):
        """Content serialization should preserve thought_signature."""
        from google.genai import types
        sig = b"test_signature_bytes_12345"
        part = types.Part(
            function_call=types.FunctionCall(name="list_tasks", args={}),
            thought_signature=sig,
        )
        content = types.Content(role="model", parts=[part])
        # Verify the signature is preserved in the Content object
        assert content.parts[0].thought_signature == sig

    def test_genai_sdk_serializes_thought_signature(self):
        """to_json_dict should include thought_signature for API transport."""
        from google.genai import types
        sig = b"test_signature"
        part = types.Part(
            function_call=types.FunctionCall(name="test_func", args={"key": "val"}),
            thought_signature=sig,
        )
        content = types.Content(role="model", parts=[part])
        json_dict = content.to_json_dict()
        # thought_signature should appear in serialized output
        assert "thought_signature" in json_dict["parts"][0]


# ── 3. Agent Thought Signature Preservation Tests ──


class TestAgentThoughtSignaturePreservation:
    """Verify that the agent preserves thought_signature in conversation history."""

    def _make_agent(self):
        from app.ai.agent import AgentService
        return AgentService(api_key="test-key", model="gemini-3.5-flash-lite")

    def _make_fc_response_with_signature(self, name, args, signature=b"mock_sig"):
        """Create a mock Gemini function call response with thought_signature."""
        from google.genai import types

        # Create a Part with function_call and thought_signature
        mock_part = MagicMock()
        mock_part.function_call = MagicMock()
        mock_part.function_call.name = name
        mock_part.function_call.args = args
        mock_part.text = None
        mock_part.thought_signature = signature

        # Create a Content object for candidate.content
        mock_content = MagicMock(spec=types.Content)
        mock_content.parts = [mock_part]
        mock_content.role = "model"

        mock_candidate = MagicMock()
        mock_candidate.content = mock_content

        mock_response = MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.text = None

        return mock_response

    def _make_text_response(self, text):
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

    @pytest.mark.asyncio
    async def test_agent_appends_candidate_content_directly(self):
        """Agent should append candidate.content (not a reconstructed copy) to history."""
        agent = self._make_agent()

        fc_resp = self._make_fc_response_with_signature(
            "list_tasks", {}, signature=b"real_signature_abc"
        )
        text_resp = self._make_text_response("Berikut tugas kamu.")

        # Track what gets passed to generate_content
        call_contents = []

        async def mock_generate(model, contents, config):
            call_contents.append(list(contents))  # Snapshot of contents at each call
            if len(call_contents) == 1:
                return fc_resp
            return text_resp

        agent._client = MagicMock()
        agent._client.aio.models.generate_content = AsyncMock(side_effect=mock_generate)

        with patch(
            "app.ai.tools.TaskService.list_tasks",
            new_callable=AsyncMock,
            return_value={"success": True, "tasks": [], "count": 0},
        ):
            await agent.process_message("Lihat tugas saya", telegram_user_id=12345)

        # Second call should contain: [user_msg, model_content (with sig), func_response]
        assert len(call_contents) == 2
        second_call_contents = call_contents[1]
        assert len(second_call_contents) == 3

        # The model content should be the EXACT same object from candidate.content
        model_content = second_call_contents[1]
        assert model_content is fc_resp.candidates[0].content, \
            "Agent should append candidate.content directly, not a reconstruction"

    @pytest.mark.asyncio
    async def test_agent_does_not_strip_thought_signature(self):
        """Agent must not construct new Content/Part objects that would strip thought_signature."""
        agent = self._make_agent()

        fc_resp = self._make_fc_response_with_signature(
            "create_task", {"title": "Test"}, signature=b"important_signature"
        )
        text_resp = self._make_text_response("Tugas berhasil dibuat!")

        captured_contents = []

        async def mock_generate(model, contents, config):
            captured_contents.append(list(contents))
            if len(captured_contents) == 1:
                return fc_resp
            return text_resp

        agent._client = MagicMock()
        agent._client.aio.models.generate_content = AsyncMock(side_effect=mock_generate)

        with patch(
            "app.ai.tools.TaskService.create_task",
            new_callable=AsyncMock,
            return_value={"success": True, "task_id": 1, "title": "Test"},
        ):
            await agent.process_message("Buat tugas test", telegram_user_id=12345)

        # Verify the model response in history has thought_signature
        model_content = captured_contents[1][1]
        model_part = model_content.parts[0]
        assert hasattr(model_part, "thought_signature")
        assert model_part.thought_signature == b"important_signature"

    @pytest.mark.asyncio
    async def test_multi_turn_preserves_all_signatures(self):
        """Multi-turn tool calling should preserve thought_signatures from all turns."""
        agent = self._make_agent()

        fc_resp1 = self._make_fc_response_with_signature(
            "list_tasks", {}, signature=b"sig_A"
        )
        fc_resp2 = self._make_fc_response_with_signature(
            "complete_task", {"task_id": 1}, signature=b"sig_B"
        )
        text_resp = self._make_text_response("Done!")

        captured = []

        async def mock_generate(model, contents, config):
            captured.append(list(contents))
            idx = len(captured)
            if idx == 1:
                return fc_resp1
            elif idx == 2:
                return fc_resp2
            return text_resp

        agent._client = MagicMock()
        agent._client.aio.models.generate_content = AsyncMock(side_effect=mock_generate)

        with patch(
            "app.ai.tools.TaskService.list_tasks",
            new_callable=AsyncMock,
            return_value={"success": True, "tasks": [{"task_id": 1}], "count": 1},
        ):
            with patch(
                "app.ai.tools.TaskService.complete_task",
                new_callable=AsyncMock,
                return_value={"success": True, "task_id": 1, "status": "completed"},
            ):
                result = await agent.process_message("Selesaikan tugas", telegram_user_id=12345)

        assert result == "Done!"

        # Third call (text response) should have 5 items:
        # [user_msg, model_fc1+sigA, func_resp1, model_fc2+sigB, func_resp2]
        final_contents = captured[2]
        assert len(final_contents) == 5

        # Both model responses should be the original objects with signatures
        assert final_contents[1] is fc_resp1.candidates[0].content
        assert final_contents[3] is fc_resp2.candidates[0].content


# ── 4. Requirements Validation ─────────────────


class TestRequirementsValidation:
    def test_requirements_has_minimum_genai_version(self):
        """requirements.txt should specify google-genai >= 1.50.0."""
        req_path = Path(__file__).parent.parent / "requirements.txt"
        content = req_path.read_text()
        assert "google-genai" in content
        # Should NOT pin to old version
        assert "google-genai==1.16.1" not in content, \
            "google-genai==1.16.1 does not support Gemini 3 thought_signature"
        # Should require >= 1.50.0
        assert ">=1.50.0" in content or "google-genai>=" in content


# ── 5. Regression: Agent Still Works ───────────


class TestAgentRegression:
    def _make_agent(self):
        from app.ai.agent import AgentService
        return AgentService(api_key="test-key", model="gemini-2.0-flash")

    def _make_text_response(self, text):
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

    @pytest.mark.asyncio
    async def test_conversational_still_works(self):
        """Non-tool messages should still return text responses."""
        agent = self._make_agent()
        text_resp = self._make_text_response("Halo!")
        agent._client = MagicMock()
        agent._client.aio.models.generate_content = AsyncMock(return_value=text_resp)

        result = await agent.process_message("Halo", telegram_user_id=1)
        assert result == "Halo!"

    @pytest.mark.asyncio
    async def test_list_tasks_tool_still_registered(self):
        """list_tasks should still be in TASK_TOOLS."""
        from app.ai.tools import TASK_TOOLS
        names = [fd.name for fd in TASK_TOOLS.function_declarations]
        assert "list_tasks" in names

    @pytest.mark.asyncio
    async def test_execute_tool_still_works(self):
        """execute_tool should still route to TaskService."""
        from app.ai.tools import execute_tool
        from app.services.task_service import TaskService

        with patch.object(
            TaskService, "list_tasks",
            new_callable=AsyncMock,
            return_value={"success": True, "tasks": [], "count": 0},
        ):
            result = await execute_tool("list_tasks", {}, telegram_user_id=123)
        assert result["success"] is True
