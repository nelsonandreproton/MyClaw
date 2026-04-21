from __future__ import annotations

import logging
from typing import Any

from memory.store import MemoryStore

logger = logging.getLogger(__name__)


class SchedulerManager:
    """Stub — full implementation in Session 5."""

    def __init__(self, store: MemoryStore):
        self._store = store

    async def start(self) -> None:
        logger.debug("SchedulerManager.start() — stub")

    async def stop(self) -> None:
        logger.debug("SchedulerManager.stop() — stub")

    def list_jobs(self) -> list[dict[str, Any]]:
        return []

    async def add_job(self, skill_name: str, cron_expr: str) -> int | None:
        logger.debug("SchedulerManager.add_job() — stub")
        return None

    async def pause_job(self, job_id: str) -> None:
        logger.debug("SchedulerManager.pause_job() — stub")

    async def resume_job(self, job_id: str) -> None:
        logger.debug("SchedulerManager.resume_job() — stub")

    async def delete_job(self, job_id: str) -> None:
        logger.debug("SchedulerManager.delete_job() — stub")

    async def run_now(self, job_id: str) -> None:
        logger.debug("SchedulerManager.run_now() — stub")
