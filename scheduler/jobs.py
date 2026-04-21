from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from errors import SchedulerError

if TYPE_CHECKING:
    from scheduler.manager import SchedulerManager
    from skills.runner import SkillDefinition, SkillRunner

logger = logging.getLogger(__name__)


async def job_executor(
    job_id: int,
    skill_name: str,
    runner: SkillRunner,
    send_fn: Callable[[str], Coroutine],
    manager: SchedulerManager,
) -> None:
    """Called by APScheduler for every scheduled tick.

    Errors are caught and reported via *send_fn* so the scheduler keeps running.
    """
    logger.info("Running scheduled job id=%d skill='%s'", job_id, skill_name)
    try:
        skill = runner.skills.get(skill_name)
        if not skill:
            raise SchedulerError(f"Skill '{skill_name}' not found for job id={job_id}")

        await runner.run_skill(
            skill,
            f"[cron job: {skill_name}]",
            context_manager=None,
            llm_client=manager.llm_client,
            send_fn=send_fn,
        )
        await manager.on_job_success(job_id)

    except Exception as exc:
        logger.exception("Job id=%d skill='%s' failed: %s", job_id, skill_name, exc)
        try:
            await send_fn(f"⚠️ Cron job *{skill_name}* falhou: `{exc}`")
        except Exception:
            pass


async def register_builtin_cron_jobs(
    manager: SchedulerManager,
    skills: dict[str, SkillDefinition],
) -> None:
    """Register skills that declare a 'cron' field, skipping those already in DB."""
    for skill in skills.values():
        if not skill.cron:
            continue
        existing = await manager.get_job_by_skill(skill.name)
        if existing:
            logger.debug(
                "Builtin cron for '%s' already registered (id=%d)", skill.name, existing.id
            )
            continue
        job_id = await manager.add_job(skill.name, skill.cron)
        logger.info(
            "Registered builtin cron for '%s': %s (job id=%d)",
            skill.name,
            skill.cron,
            job_id,
        )
