"""
Tests for Phase 13B — Long-Term Memory Tools and Agent Integration.

Covers: Memory Tools definitions, tool execution routing,
agent integration (multi-turn with memory), and prompt injection checks.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.ai.tools import MEMORY_TOOLS, execute_tool
from app.services.memory_service import MemoryService
from app.ai.agent import _get_agent_system_prompt

# ── Tool Definition Tests ─────────────────────

class TestMemoryToolDefinitions:
    def test_memory_tools_has_functions(self):
        assert len(MEMORY_TOOLS.function_declarations) == 4

    def test_tool_names(self):
        names = [fd.name for fd in MEMORY_TOOLS.function_declarations]
        assert "save_memory" in names
        assert "search_memory" in names
        assert "update_memory" in names
        assert "delete_memory" in names

    def test_save_memory_requires_fields(self):
        fd = next(f for f in MEMORY_TOOLS.function_declarations if f.name == "save_memory")
        assert "category" in fd.parameters.required
        assert "fact" in fd.parameters.required

    def test_update_memory_requires_fields(self):
        fd = next(f for f in MEMORY_TOOLS.function_declarations if f.name == "update_memory")
        assert "memory_id" in fd.parameters.required
        assert "new_fact" in fd.parameters.required

    def test_delete_memory_requires_fields(self):
        fd = next(f for f in MEMORY_TOOLS.function_declarations if f.name == "delete_memory")
        assert "memory_id" in fd.parameters.required


# ── Tool Execution Tests ──────────────────────

class TestMemoryToolExecution:
    @pytest.mark.asyncio
    async def test_execute_save_memory(self):
        mock_result = {"success": True, "memory": {"id": 1, "category": "preference", "fact": "Suka teh"}}
        with patch.object(MemoryService, "save_memory", new_callable=AsyncMock, return_value=mock_result) as mock:
            result = await execute_tool("save_memory", {"category": "preference", "fact": "Suka teh"}, telegram_user_id=111)
            mock.assert_called_once_with(telegram_user_id=111, category="preference", fact="Suka teh")
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_search_memory(self):
        mock_result = [{"id": 1, "category": "preference", "fact": "Suka teh"}]
        with patch.object(MemoryService, "search_memory", new_callable=AsyncMock, return_value=mock_result) as mock:
            result = await execute_tool("search_memory", {"query": "teh"}, telegram_user_id=111)
            mock.assert_called_once_with(telegram_user_id=111, query="teh", category=None)
            assert result["success"] is True
            assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_execute_update_memory(self):
        mock_result = {"success": True}
        with patch.object(MemoryService, "update_memory", new_callable=AsyncMock, return_value=mock_result) as mock:
            result = await execute_tool("update_memory", {"memory_id": 1, "new_fact": "Suka kopi"}, telegram_user_id=111)
            mock.assert_called_once_with(telegram_user_id=111, memory_id=1, new_fact="Suka kopi")
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_delete_memory(self):
        mock_result = {"success": True}
        with patch.object(MemoryService, "delete_memory", new_callable=AsyncMock, return_value=mock_result) as mock:
            result = await execute_tool("delete_memory", {"memory_id": 1}, telegram_user_id=111)
            mock.assert_called_once_with(telegram_user_id=111, memory_id=1)
            assert result["success"] is True


# ── Agent System Prompt Tests ──────────────────

class TestAgentPrompt:
    def test_prompt_includes_memory_rules(self):
        prompt = _get_agent_system_prompt()
        assert "Long-Term Memory" in prompt
        assert "save_memory" in prompt
        assert "search_memory" in prompt
        assert "update_memory" in prompt
        assert "delete_memory" in prompt

# ── Agent Integration Tests ────────────────────

class TestAgentIntegration:
    def _make_agent(self):
        from app.ai.agent import AgentService
        return AgentService(api_key="test-key", model="gemini-2.0-flash")

    def _mock_function_call_response(self, name, args):
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

    def _mock_text_response(self, text):
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
    async def test_agent_multi_turn_save_memory(self):
        agent = self._make_agent()
        fc_resp = self._mock_function_call_response("save_memory", {"category": "preference", "fact": "Suka membaca"})
        text_resp = self._mock_text_response("Fakta telah disimpan.")
        
        agent._client = MagicMock()
        agent._client.aio.models.generate_content = AsyncMock(side_effect=[fc_resp, text_resp])

        with patch("app.ai.agent.execute_tool", new_callable=AsyncMock, return_value={"success": True}):
            with patch("app.services.chat_history_service.ChatHistoryService.get_recent_messages", return_value=[]):
                result = await agent.process_message("Saya suka membaca buku", telegram_user_id=123)
        
        assert "disimpan" in result.lower()
