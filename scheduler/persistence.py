from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from memory.store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass
class JobRecord:
    id: int
    skill_name: str
    cron_expr: str
    enabled: bool
    created_at: str
    next_run: str | None
    last_run: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "skill_name": self.skill_name,
            "cron_expr": self.cron_expr,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "next_run": self.next_run or "n/d",
            "last_run": self.last_run or "nunca",
        }


def _row_to_record(row: Any) -> JobRecord:
    return JobRecord(
        id=row["id"],
        skill_name=row["skill_name"],
        cron_expr=row["cron_expr"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        next_run=row["next_run"],
        last_run=row["last_run"],
    )


async def load_jobs_from_db(db: MemoryStore) -> list[JobRecord]:
    rows = await db.fetchall(
        "SELECT id, skill_name, cron_expr, enabled, created_at, next_run, last_run "
        "FROM cron_jobs ORDER BY id ASC"
    )
    return [_row_to_record(r) for r in rows]


async def save_job(db: MemoryStore, skill_name: str, cron_expr: str) -> int:
    cursor = await db.execute(
        "INSERT INTO cron_jobs (skill_name, cron_expr) VALUES (?, ?)",
        (skill_name, cron_expr),
    )
    job_id = cursor.lastrowid
    logger.debug("Saved cron job id=%d skill=%s expr='%s'", job_id, skill_name, cron_expr)
    return job_id


async def update_job_last_run(db: MemoryStore, job_id: int) -> None:
    await db.execute(
        "UPDATE cron_jobs SET last_run = CURRENT_TIMESTAMP WHERE id = ?",
        (job_id,),
    )


async def update_job_next_run(db: MemoryStore, job_id: int, next_run: datetime | None) -> None:
    value = next_run.isoformat() if next_run else None
    await db.execute(
        "UPDATE cron_jobs SET next_run = ? WHERE id = ?",
        (value, job_id),
    )


async def set_job_enabled(db: MemoryStore, job_id: int, enabled: bool) -> None:
    await db.execute(
        "UPDATE cron_jobs SET enabled = ? WHERE id = ?",
        (int(enabled), job_id),
    )


async def delete_job(db: MemoryStore, job_id: int) -> None:
    await db.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
    logger.debug("Deleted cron job id=%d", job_id)


async def get_job_by_id(db: MemoryStore, job_id: int) -> JobRecord | None:
    row = await db.fetchone(
        "SELECT id, skill_name, cron_expr, enabled, created_at, next_run, last_run "
        "FROM cron_jobs WHERE id = ?",
        (job_id,),
    )
    return _row_to_record(row) if row else None


async def get_job_by_skill(db: MemoryStore, skill_name: str) -> JobRecord | None:
    row = await db.fetchone(
        "SELECT id, skill_name, cron_expr, enabled, created_at, next_run, last_run "
        "FROM cron_jobs WHERE skill_name = ? ORDER BY id DESC LIMIT 1",
        (skill_name,),
    )
    return _row_to_record(row) if row else None
