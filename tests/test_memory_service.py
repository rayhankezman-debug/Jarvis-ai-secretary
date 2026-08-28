import pytest
from app.services.memory_service import MemoryService
from app.database.models import LongTermMemory
from sqlalchemy import select
from app.database.session import get_db_session

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.database.base import Base
from unittest.mock import patch
from contextlib import asynccontextmanager

pytestmark = pytest.mark.asyncio

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

@pytest.fixture(autouse=True)
def mock_db_session(test_session_factory):
    """Patch get_db_session to use our test session factory."""
    @asynccontextmanager
    async def get_test_session():
        async with test_session_factory() as session:
            yield session

    with patch("app.services.memory_service.get_db_session", new=get_test_session), \
         patch("tests.test_memory_service.get_db_session", new=get_test_session):
        yield

@pytest.fixture
async def clear_memories(test_session_factory):
    """Fixture to clear memories before/after tests."""
    async with test_session_factory() as session:
        await session.execute(LongTermMemory.__table__.delete())
        await session.commit()
    yield
    async with test_session_factory() as session:
        await session.execute(LongTermMemory.__table__.delete())
        await session.commit()


async def test_save_memory(clear_memories):
    user_id = 111
    result = await MemoryService.save_memory(user_id, "preference", "Saya suka kopi")
    
    assert result["success"] is True
    assert "memory" in result
    assert result["memory"]["category"] == "preference"
    assert result["memory"]["fact"] == "Saya suka kopi"
    
    # Verify in DB
    async with get_db_session() as session:
        stmt = select(LongTermMemory).where(LongTermMemory.telegram_user_id == user_id)
        db_memories = (await session.execute(stmt)).scalars().all()
        assert len(db_memories) == 1
        assert db_memories[0].fact == "Saya suka kopi"


async def test_search_memory_by_keyword(clear_memories):
    user_id = 222
    await MemoryService.save_memory(user_id, "preference", "Saya suka kopi")
    await MemoryService.save_memory(user_id, "preference", "Saya suka teh")
    await MemoryService.save_memory(user_id, "habit", "Bangun jam 5 pagi")
    
    results = await MemoryService.search_memory(user_id, query="kopi")
    assert len(results) == 1
    assert results[0]["fact"] == "Saya suka kopi"
    
    results_teh = await MemoryService.search_memory(user_id, query="TEH") # Case insensitive
    assert len(results_teh) == 1
    assert results_teh[0]["fact"] == "Saya suka teh"


async def test_search_memory_by_category(clear_memories):
    user_id = 333
    await MemoryService.save_memory(user_id, "preference", "Suka warna biru")
    await MemoryService.save_memory(user_id, "habit", "Olahraga sore")
    
    results = await MemoryService.search_memory(user_id, query="", category="habit")
    assert len(results) == 1
    assert results[0]["fact"] == "Olahraga sore"


async def test_search_memory_empty(clear_memories):
    user_id = 444
    await MemoryService.save_memory(user_id, "preference", "Suka kucing")
    
    results = await MemoryService.search_memory(user_id, query="anjing")
    assert len(results) == 0


async def test_update_memory(clear_memories):
    user_id = 555
    save_result = await MemoryService.save_memory(user_id, "preference", "Suka kopi")
    mem_id = save_result["memory"]["id"]
    
    update_result = await MemoryService.update_memory(user_id, mem_id, "Tidak suka kopi lagi")
    assert update_result["success"] is True
    assert update_result["memory"]["fact"] == "Tidak suka kopi lagi"
    
    results = await MemoryService.search_memory(user_id, query="")
    assert len(results) == 1
    assert results[0]["fact"] == "Tidak suka kopi lagi"


async def test_delete_memory(clear_memories):
    user_id = 666
    save_result = await MemoryService.save_memory(user_id, "preference", "Suka es krim")
    mem_id = save_result["memory"]["id"]
    
    delete_result = await MemoryService.delete_memory(user_id, mem_id)
    assert delete_result["success"] is True
    
    results = await MemoryService.search_memory(user_id, query="")
    assert len(results) == 0


async def test_user_isolation(clear_memories):
    user_a = 777
    user_b = 888
    
    # User A saves memory
    save_a = await MemoryService.save_memory(user_a, "identity", "Nama saya Budi")
    mem_id_a = save_a["memory"]["id"]
    
    # User B should not see User A's memory
    results_b = await MemoryService.search_memory(user_b, query="Budi")
    assert len(results_b) == 0
    
    # User B tries to update User A's memory
    update_attempt = await MemoryService.update_memory(user_b, mem_id_a, "Nama saya Joko")
    assert update_attempt["success"] is False
    assert "not found or unauthorized" in update_attempt["error"]
    
    # User B tries to delete User A's memory
    delete_attempt = await MemoryService.delete_memory(user_b, mem_id_a)
    assert delete_attempt["success"] is False
    assert "not found or unauthorized" in delete_attempt["error"]
    
    # Verify User A's memory is unchanged
    results_a = await MemoryService.search_memory(user_a, query="")
    assert len(results_a) == 1
    assert results_a[0]["fact"] == "Nama saya Budi"
