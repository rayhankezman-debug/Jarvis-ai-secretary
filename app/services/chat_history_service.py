"""
Service for managing short-term conversational memory.
"""

from typing import List
from sqlalchemy import select, desc

from app.core.logging import get_logger
from app.database.models import ConversationMessage, MessageRole
from app.database.session import get_db_session

logger = get_logger(__name__)


class ChatHistoryService:
    """
    Manages short-term conversation history for AgentService context.
    """

    @staticmethod
    async def add_message(telegram_user_id: int, role: MessageRole, content: str) -> None:
        """
        Save a new message to the conversation history.
        """
        try:
            async with get_db_session() as session:
                msg = ConversationMessage(
                    telegram_user_id=telegram_user_id,
                    role=role,
                    content=content,
                )
                session.add(msg)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to add chat history message for user {telegram_user_id}: {e}")
            # We don't raise here because chat history failure shouldn't crash the main flow

    @staticmethod
    async def get_recent_messages(telegram_user_id: int, limit: int = 10) -> List[ConversationMessage]:
        """
        Retrieve the most recent messages for a user, ordered chronologically.
        """
        try:
            async with get_db_session() as session:
                # Query in descending order to get the most recent, then reverse in Python
                # so they are chronological (oldest to newest)
                query = (
                    select(ConversationMessage)
                    .where(ConversationMessage.telegram_user_id == telegram_user_id)
                    .order_by(desc(ConversationMessage.id))
                    .limit(limit)
                )
                result = await session.execute(query)
                messages = result.scalars().all()
                
                # Reverse to get chronological order (oldest first)
                return list(reversed(messages))
        except Exception as e:
            logger.error(f"Failed to fetch recent messages for user {telegram_user_id}: {e}")
            return []
