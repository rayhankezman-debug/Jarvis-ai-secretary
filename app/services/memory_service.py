"""
Service for managing long-term memory/facts about the user.
"""

from typing import List, Optional
from sqlalchemy import select, and_, or_

from app.core.logging import get_logger
from app.database.models import LongTermMemory
from app.database.session import get_db_session

logger = get_logger(__name__)


class MemoryService:
    """
    Service to handle CRUD operations for long-term user memories.
    """

    @staticmethod
    async def save_memory(telegram_user_id: int, category: str, fact: str) -> dict:
        """
        Save a new memory fact for a user.
        """
        try:
            async with get_db_session() as session:
                memory = LongTermMemory(
                    telegram_user_id=telegram_user_id,
                    category=category,
                    fact=fact,
                )
                session.add(memory)
                await session.commit()
                await session.refresh(memory)
                
                logger.info(f"Saved memory for user {telegram_user_id}: {fact[:30]}...")
                return {
                    "success": True,
                    "memory": {
                        "id": memory.id,
                        "category": memory.category,
                        "fact": memory.fact,
                    }
                }
        except Exception as e:
            logger.error(f"Failed to save memory for user {telegram_user_id}: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def search_memory(telegram_user_id: int, query: str, category: Optional[str] = None) -> List[dict]:
        """
        Search for memories using a keyword query and optional category filter.
        Uses PostgreSQL ILIKE for case-insensitive substring matching.
        """
        try:
            async with get_db_session() as session:
                stmt = select(LongTermMemory).where(
                    LongTermMemory.telegram_user_id == telegram_user_id
                )
                
                if category:
                    stmt = stmt.where(LongTermMemory.category == category)
                    
                if query:
                    stmt = stmt.where(LongTermMemory.fact.ilike(f"%{query}%"))
                    
                stmt = stmt.order_by(LongTermMemory.created_at.desc())
                
                result = await session.execute(stmt)
                memories = result.scalars().all()
                
                return [
                    {
                        "id": m.id,
                        "category": m.category,
                        "fact": m.fact,
                        "updated_at": m.updated_at.isoformat() if m.updated_at else m.created_at.isoformat(),
                    }
                    for m in memories
                ]
        except Exception as e:
            logger.error(f"Failed to search memory for user {telegram_user_id}: {e}")
            return []

    @staticmethod
    async def update_memory(telegram_user_id: int, memory_id: int, new_fact: str) -> dict:
        """
        Update an existing memory fact.
        Validates telegram_user_id to ensure user isolation.
        """
        try:
            async with get_db_session() as session:
                stmt = select(LongTermMemory).where(
                    and_(
                        LongTermMemory.id == memory_id,
                        LongTermMemory.telegram_user_id == telegram_user_id
                    )
                )
                result = await session.execute(stmt)
                memory = result.scalar_one_or_none()
                
                if not memory:
                    logger.warning(f"Memory {memory_id} not found for user {telegram_user_id} during update")
                    return {"success": False, "error": "Memory not found or unauthorized"}
                    
                memory.fact = new_fact
                await session.commit()
                await session.refresh(memory)
                
                logger.info(f"Updated memory {memory_id} for user {telegram_user_id}")
                return {
                    "success": True,
                    "memory": {
                        "id": memory.id,
                        "category": memory.category,
                        "fact": memory.fact,
                    }
                }
        except Exception as e:
            logger.error(f"Failed to update memory {memory_id} for user {telegram_user_id}: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    async def delete_memory(telegram_user_id: int, memory_id: int) -> dict:
        """
        Delete a memory fact.
        Validates telegram_user_id to ensure user isolation.
        """
        try:
            async with get_db_session() as session:
                stmt = select(LongTermMemory).where(
                    and_(
                        LongTermMemory.id == memory_id,
                        LongTermMemory.telegram_user_id == telegram_user_id
                    )
                )
                result = await session.execute(stmt)
                memory = result.scalar_one_or_none()
                
                if not memory:
                    logger.warning(f"Memory {memory_id} not found for user {telegram_user_id} during delete")
                    return {"success": False, "error": "Memory not found or unauthorized"}
                    
                await session.delete(memory)
                await session.commit()
                
                logger.info(f"Deleted memory {memory_id} for user {telegram_user_id}")
                return {"success": True}
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id} for user {telegram_user_id}: {e}")
            return {"success": False, "error": str(e)}
