import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def store(tmp_path):
    from memory.store import MemoryStore
    from memory.migrations import run_migrations

    s = MemoryStore(str(tmp_path / "test.db"))
    await s.init()
    await run_migrations(s)
    yield s
    await s.close()
