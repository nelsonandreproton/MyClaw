import logging
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class MemoryStore:
    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.commit()
        logger.debug("MemoryStore initialized at %s", self._db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.debug("MemoryStore closed")

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        self._assert_open()
        cursor = await self._conn.execute(sql, params)  # type: ignore[union-attr]
        await self._conn.commit()  # type: ignore[union-attr]
        return cursor

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        self._assert_open()
        async with self._conn.execute(sql, params) as cursor:  # type: ignore[union-attr]
            return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        self._assert_open()
        async with self._conn.execute(sql, params) as cursor:  # type: ignore[union-attr]
            return await cursor.fetchall()

    def _assert_open(self) -> None:
        if self._conn is None:
            raise RuntimeError("MemoryStore is not initialized. Call await store.init() first.")

    async def __aenter__(self) -> "MemoryStore":
        await self.init()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
