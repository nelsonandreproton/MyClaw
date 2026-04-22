from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from errors import SchedulerError
from memory.store import MemoryStore
from scheduler.persistence import (
    JobRecord,
    delete_job as db_delete_job,
    get_job_by_id,
    get_job_by_skill,
    load_jobs_from_db,
    save_job,
    set_job_enabled,
    update_job_last_run,
    update_job_next_run,
)

logger = logging.getLogger(__name__)

# APScheduler job id prefix so our jobs don't clash with anything else
_JOB_PREFIX = "myclaw_"


class SchedulerManager:
    def __init__(self, store: MemoryStore):
        self._store = store
        self._scheduler = AsyncIOScheduler()
        self._cron_exprs: dict[int, str] = {}  # job_id → original cron expression
        # Set by main.py after construction so jobs can call the runner
        self.skill_runner: Any = None
        self.llm_client: Any = None
        self.send_fn: Callable[[str], Coroutine] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._scheduler.start()
        jobs = await load_jobs_from_db(self._store)
        for job in jobs:
            if job.enabled:
                self._schedule(job)
        logger.info(
            "SchedulerManager started — %d job(s) loaded", len(jobs)
        )

    async def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        logger.info("SchedulerManager stopped")

    # ------------------------------------------------------------------
    # Public API (mirrors the stub interface used by bot/commands.py)
    # ------------------------------------------------------------------

    async def add_job(self, skill_name: str, cron_expr: str) -> int:
        if len(cron_expr) > 100:
            raise SchedulerError(f"Cron expression too long: {cron_expr!r}")
        try:
            CronTrigger.from_crontab(cron_expr)
        except Exception as exc:
            raise SchedulerError(f"Invalid cron expression '{cron_expr}': {exc}") from exc
        job_id = await save_job(self._store, skill_name, cron_expr)
        record = await get_job_by_id(self._store, job_id)
        if record:
            self._schedule(record)
            await self._refresh_next_run(job_id)
        logger.info("Added job id=%d skill='%s' cron='%s'", job_id, skill_name, cron_expr)
        return job_id

    async def pause_job(self, job_ref: str | int) -> None:
        record = await self._resolve(job_ref)
        if not record:
            raise SchedulerError(f"Job '{job_ref}' não encontrado.")
        apsjob = self._scheduler.get_job(_apsjob_id(record.id))
        if apsjob:
            apsjob.pause()
        await set_job_enabled(self._store, record.id, False)
        logger.info("Paused job id=%d skill='%s'", record.id, record.skill_name)

    async def resume_job(self, job_ref: str | int) -> None:
        record = await self._resolve(job_ref)
        if not record:
            raise SchedulerError(f"Job '{job_ref}' não encontrado.")
        await set_job_enabled(self._store, record.id, True)
        apsjob = self._scheduler.get_job(_apsjob_id(record.id))
        if apsjob:
            apsjob.resume()
        else:
            # Job was removed from scheduler while paused — re-add it
            self._schedule(record)
        await self._refresh_next_run(record.id)
        logger.info("Resumed job id=%d skill='%s'", record.id, record.skill_name)

    async def delete_job(self, job_ref: str | int) -> None:
        record = await self._resolve(job_ref)
        if not record:
            raise SchedulerError(f"Job '{job_ref}' não encontrado.")
        apsjob = self._scheduler.get_job(_apsjob_id(record.id))
        if apsjob:
            apsjob.remove()
        self._cron_exprs.pop(record.id, None)
        await db_delete_job(self._store, record.id)
        logger.info("Deleted job id=%d skill='%s'", record.id, record.skill_name)

    async def run_now(self, job_ref: str | int) -> None:
        record = await self._resolve(job_ref)
        if not record:
            raise SchedulerError(f"Job '{job_ref}' não encontrado.")
        await self._fire(record)

    def list_jobs(self) -> list[dict[str, Any]]:
        """Synchronous snapshot — used by bot/commands.py inside async handlers."""
        results: list[dict[str, Any]] = []
        for j in self._scheduler.get_jobs():
            try:
                job_id = int(j.id.removeprefix(_JOB_PREFIX))
            except ValueError:
                continue
            kwargs = j.kwargs or {}
            skill_name = kwargs.get("skill_name", "?")
            cron_expr = self._cron_exprs.get(job_id, str(j.trigger))
            next_run = j.next_run_time.isoformat() if j.next_run_time else "n/d"
            results.append(
                {
                    "id": job_id,
                    "skill_name": skill_name,
                    "cron_expr": cron_expr,
                    "enabled": j.next_run_time is not None,
                    "next_run": next_run,
                }
            )
        return results

    # ------------------------------------------------------------------
    # Helpers for scheduler/jobs.py
    # ------------------------------------------------------------------

    async def on_job_success(self, job_id: int) -> None:
        await update_job_last_run(self._store, job_id)
        await self._refresh_next_run(job_id)

    async def get_job_by_skill(self, skill_name: str) -> JobRecord | None:
        return await get_job_by_skill(self._store, skill_name)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _schedule(self, record: JobRecord) -> None:
        from scheduler.jobs import job_executor  # late import avoids circular dep

        try:
            trigger = CronTrigger.from_crontab(record.cron_expr)
        except Exception as exc:
            logger.warning(
                "Invalid cron expr '%s' for job id=%d: %s",
                record.cron_expr, record.id, exc,
            )
            return

        self._cron_exprs[record.id] = record.cron_expr
        self._scheduler.add_job(
            self._run_job_wrapper,
            trigger=trigger,
            id=_apsjob_id(record.id),
            kwargs={"job_id": record.id, "skill_name": record.skill_name},
            replace_existing=True,
            misfire_grace_time=300,
        )

    async def _run_job_wrapper(self, job_id: int, skill_name: str) -> None:
        from scheduler.jobs import job_executor

        runner = self.skill_runner
        send_fn = self.send_fn
        if not runner or not send_fn:
            logger.warning("Job id=%d: runner or send_fn not set, skipping", job_id)
            return
        await job_executor(job_id, skill_name, runner, send_fn, self)

    async def _fire(self, record: JobRecord) -> None:
        """Execute a job immediately, outside its schedule."""
        await self._run_job_wrapper(record.id, record.skill_name)

    async def _refresh_next_run(self, job_id: int) -> None:
        apsjob = self._scheduler.get_job(_apsjob_id(job_id))
        next_run = apsjob.next_run_time if apsjob else None
        await update_job_next_run(self._store, job_id, next_run)

    async def _resolve(self, job_ref: str | int) -> JobRecord | None:
        """Accept either a numeric id or a skill_name string."""
        if isinstance(job_ref, int) or (isinstance(job_ref, str) and job_ref.isdigit()):
            return await get_job_by_id(self._store, int(job_ref))
        return await get_job_by_skill(self._store, str(job_ref))


def _apsjob_id(job_id: int) -> str:
    return f"{_JOB_PREFIX}{job_id}"
