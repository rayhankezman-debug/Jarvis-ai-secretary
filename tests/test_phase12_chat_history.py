import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from google.genai import types
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.database.base import Base

from app.database.models import ConversationMessage, MessageRole
from app.services.chat_history_service import ChatHistoryService
from app.ai.agent import AgentService
from app.telegram.handlers import handle_text_message
from app.ai.base import LLMError


@pytest.fixture
async def test_engine():
    """Create an in-memory SQLite async engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",  # In-memory SQLite
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


from contextlib import asynccontextmanager

@pytest.fixture(autouse=True)
def mock_db_session(test_session_factory):
    """Patch get_db_session to use our test session factory."""
    @asynccontextmanager
    async def get_test_session():
        async with test_session_factory() as session:
            yield session

    with patch("app.services.chat_history_service.get_db_session", new=get_test_session):
        yield


@pytest.mark.asyncio
async def test_chat_history_persistence():
    """Test saving and retrieving messages."""
    await ChatHistoryService.add_message(111, MessageRole.USER, "Halo!")
    await ChatHistoryService.add_message(111, MessageRole.MODEL, "Hai, ada yang bisa dibantu?")

    messages = await ChatHistoryService.get_recent_messages(111)
    
    assert len(messages) == 2
    assert messages[0].role == MessageRole.USER
    assert messages[0].content == "Halo!"
    assert messages[1].role == MessageRole.MODEL
    assert messages[1].content == "Hai, ada yang bisa dibantu?"


@pytest.mark.asyncio
async def test_ordering():
    """Test messages are returned chronologically (oldest first)."""
    await ChatHistoryService.add_message(222, MessageRole.USER, "Msg 1")
    await ChatHistoryService.add_message(222, MessageRole.MODEL, "Msg 2")
    await ChatHistoryService.add_message(222, MessageRole.USER, "Msg 3")

    messages = await ChatHistoryService.get_recent_messages(222)
    assert len(messages) == 3
    assert messages[0].content == "Msg 1"
    assert messages[1].content == "Msg 2"
    assert messages[2].content == "Msg 3"


@pytest.mark.asyncio
async def test_user_isolation():
    """Test history from user A doesn't show for user B."""
    await ChatHistoryService.add_message(333, MessageRole.USER, "User A msg")
    await ChatHistoryService.add_message(444, MessageRole.USER, "User B msg")

    messages_a = await ChatHistoryService.get_recent_messages(333)
    assert len(messages_a) == 1
    assert messages_a[0].content == "User A msg"


@pytest.mark.asyncio
async def test_limit():
    """Test that only limit messages are returned."""
    for i in range(15):
        await ChatHistoryService.add_message(555, MessageRole.USER, f"Msg {i}")

    messages = await ChatHistoryService.get_recent_messages(555, limit=10)
    assert len(messages) == 10
    assert messages[0].content == "Msg 5"
    assert messages[-1].content == "Msg 14"


@pytest.mark.asyncio
async def test_agent_context_injection():
    """Test AgentService loads and injects context before sending to Gemini."""
    await ChatHistoryService.add_message(666, MessageRole.USER, "History 1")
    await ChatHistoryService.add_message(666, MessageRole.MODEL, "History 2")
    await ChatHistoryService.add_message(666, MessageRole.USER, "Current Message")

    agent = AgentService(api_key="fake")
    
    with patch.object(agent._client.aio.models, "generate_content", new_callable=AsyncMock) as mock_gen:
        mock_resp = MagicMock()
        mock_resp.text = "Response text"
        mock_resp.candidates = [MagicMock()]
        mock_resp.candidates[0].content.parts = [MagicMock(function_call=None)]
        mock_gen.return_value = mock_resp

        await agent.process_message("Current Message", telegram_user_id=666)

        mock_gen.assert_called_once()
        contents_sent = mock_gen.call_args.kwargs["contents"]
        
        # Should have 3 messages
        assert len(contents_sent) == 3
        assert contents_sent[0].role == "user"
        assert contents_sent[0].parts[0].text == "History 1"
        assert contents_sent[1].role == "model"
        assert contents_sent[1].parts[0].text == "History 2"
        assert contents_sent[2].role == "user"
        assert contents_sent[2].parts[0].text == "Current Message"


@pytest.mark.asyncio
async def test_agent_no_double_message():
    """Test that if handler didn't save the message yet, agent appends it exactly once."""
    await ChatHistoryService.add_message(777, MessageRole.USER, "History 1")
    
    agent = AgentService(api_key="fake")
    
    with patch.object(agent._client.aio.models, "generate_content", new_callable=AsyncMock) as mock_gen:
        mock_resp = MagicMock()
        mock_resp.text = "Response text"
        mock_resp.candidates = [MagicMock()]
        mock_resp.candidates[0].content.parts = [MagicMock(function_call=None)]
        mock_gen.return_value = mock_resp

        # We simulate passing a NEW message that is NOT in the DB yet
        await agent.process_message("Current Message", telegram_user_id=777)

        contents_sent = mock_gen.call_args.kwargs["contents"]
        
        # Should have 2 messages: the one from DB, and the current message appended manually
        assert len(contents_sent) == 2
        assert contents_sent[0].parts[0].text == "History 1"
        assert contents_sent[1].parts[0].text == "Current Message"


@pytest.mark.asyncio
async def test_error_handling_not_saved():
    """Test that if agent fails, the error is NOT saved as assistant response."""
    update = MagicMock()
    update.effective_user.id = 888
    update.message.text = "Bad message"
    update.message.reply_text = AsyncMock()
    
    # Mock get_agent to return an agent that raises an error
    mock_agent = MagicMock()
    mock_agent.process_message = AsyncMock(side_effect=LLMError("Boom", provider="gemini"))
    
    with patch("app.telegram.handlers.get_agent", return_value=mock_agent) if False else patch("app.ai.agent.get_agent", return_value=mock_agent):
        await handle_text_message(update, None)
        
    messages = await ChatHistoryService.get_recent_messages(888)
    
    # User message SHOULD be saved (saved before agent is called)
    assert len(messages) == 1
    assert messages[0].role == MessageRole.USER
    assert messages[0].content == "Bad message"
    
    # Error response SHOULD NOT be saved in DB
    update.message.reply_text.assert_called_once()
    assert "gangguan sementara" in update.message.reply_text.call_args[0][0].lower()


@pytest.mark.asyncio
async def test_tool_calling_regression():
    """Test that history injection does not break multi-turn tool calling."""
    agent = AgentService(api_key="fake")
    
    with patch.object(agent._client.aio.models, "generate_content", new_callable=AsyncMock) as mock_gen, \
         patch("app.ai.agent.execute_tool", new_callable=AsyncMock) as mock_execute:
        
        # Turn 1: model returns function call
        mock_resp_1 = MagicMock()
        mock_resp_1.text = None
        mock_resp_1.candidates = [MagicMock()]
        
        fc = MagicMock()
        fc.name = "list_tasks"
        fc.args = {"title_search": "test"}
        
        part_fc = MagicMock(function_call=fc)
        mock_resp_1.candidates[0].content.parts = [part_fc]
        
        # Turn 2: model returns text
        mock_resp_2 = MagicMock()
        mock_resp_2.text = "Ini daftar tasknya."
        mock_resp_2.candidates = [MagicMock()]
        mock_resp_2.candidates[0].content.parts = [MagicMock(function_call=None)]
        
        mock_gen.side_effect = [mock_resp_1, mock_resp_2]
        
        mock_execute.return_value = {"tasks": []}
        
        response = await agent.process_message("List tasks", telegram_user_id=999)
        
        assert response == "Ini daftar tasknya."
        assert mock_gen.call_count == 2
        assert mock_execute.call_count == 1
        
        # Check that the tool result was appended
        contents_turn_2 = mock_gen.call_args_list[1].kwargs["contents"]
        assert contents_turn_2[-1].parts[0].function_response.name == "list_tasks"
