from __future__ import annotations

import logging
from typing import Any

from memory.store import MemoryStore

logger = logging.getLogger(__name__)


class WatchdogManager:
    """Stub — full implementation in Session 7."""

    def __init__(self, store: MemoryStore):
        self._store = store

    async def start(self) -> None:
        logger.debug("WatchdogManager.start() — stub")

    async def stop(self) -> None:
        logger.debug("WatchdogManager.stop() — stub")

    def list_watches(self) -> list[dict[str, Any]]:
        return []

    async def add_watch(self, path: str, pattern: str | None, skill_name: str | None) -> int:
        logger.debug("WatchdogManager.add_watch() — stub")
        return -1

    async def remove_watch(self, watch_id: int) -> None:
        logger.debug("WatchdogManager.remove_watch() — stub")
