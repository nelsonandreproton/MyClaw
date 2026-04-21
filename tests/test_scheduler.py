"""Tests for scheduler persistence and manager."""
import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _insert_skill(store, name: str) -> None:
    """Insert a skill row so cron_jobs FK constraint is satisfied."""
    await store.execute(
        "INSERT OR IGNORE INTO skills (name, description, md_path) VALUES (?, ?, '')",
        (name, f"Test skill {name}"),
    )


@pytest_asyncio.fixture
async def scheduler(store):
    from scheduler.manager import SchedulerManager

    mgr = SchedulerManager(store)
    await mgr.start()
    yield mgr
    await mgr.stop()


# ---------------------------------------------------------------------------
# Persistence functions (lower-level)
# ---------------------------------------------------------------------------

class TestSchedulerPersistence:
    async def test_save_and_load_job(self, store):
        from scheduler.persistence import save_job, load_jobs_from_db

        await _insert_skill(store, "briefing")
        job_id = await save_job(store, "briefing", "0 8 * * 1-5")

        jobs = await load_jobs_from_db(store)
        assert len(jobs) == 1
        assert jobs[0].id == job_id
        assert jobs[0].skill_name == "briefing"
        assert jobs[0].cron_expr == "0 8 * * 1-5"
        assert jobs[0].enabled is True

    async def test_set_job_enabled_false(self, store):
        from scheduler.persistence import save_job, set_job_enabled, get_job_by_id

        await _insert_skill(store, "test_skill")
        job_id = await save_job(store, "test_skill", "0 9 * * *")
        await set_job_enabled(store, job_id, False)

        record = await get_job_by_id(store, job_id)
        assert record.enabled is False

    async def test_delete_job_removes_from_db(self, store):
        from scheduler.persistence import save_job, delete_job, load_jobs_from_db

        await _insert_skill(store, "delete_me")
        job_id = await save_job(store, "delete_me", "0 10 * * *")
        await delete_job(store, job_id)

        jobs = await load_jobs_from_db(store)
        assert all(j.id != job_id for j in jobs)

    async def test_get_job_by_skill_name(self, store):
        from scheduler.persistence import save_job, get_job_by_skill

        await _insert_skill(store, "garmin_stats")
        await save_job(store, "garmin_stats", "0 7 * * *")

        record = await get_job_by_skill(store, "garmin_stats")
        assert record is not None
        assert record.skill_name == "garmin_stats"

    async def test_get_job_by_skill_returns_none_when_missing(self, store):
        from scheduler.persistence import get_job_by_skill

        record = await get_job_by_skill(store, "nonexistent")
        assert record is None


# ---------------------------------------------------------------------------
# SchedulerManager
# ---------------------------------------------------------------------------

class TestSchedulerManager:
    async def test_add_job_persists_to_db(self, store, scheduler):
        from scheduler.persistence import get_job_by_id

        await _insert_skill(store, "briefing")
        job_id = await scheduler.add_job("briefing", "0 8 * * 1-5")

        record = await get_job_by_id(store, job_id)
        assert record is not None
        assert record.skill_name == "briefing"
        assert record.cron_expr == "0 8 * * 1-5"

    async def test_add_job_appears_in_list(self, store, scheduler):
        await _insert_skill(store, "reminder")
        await scheduler.add_job("reminder", "30 9 * * *")

        jobs = scheduler.list_jobs()
        assert any(j["skill_name"] == "reminder" for j in jobs)

    async def test_load_jobs_on_startup(self, store):
        from scheduler.manager import SchedulerManager
        from scheduler.persistence import save_job

        # Pre-populate DB (simulates a previous run)
        await _insert_skill(store, "briefing")
        await save_job(store, "briefing", "0 8 * * 1-5")

        # New manager instance (simulates restart)
        mgr = SchedulerManager(store)
        await mgr.start()
        try:
            jobs = mgr.list_jobs()
            assert len(jobs) == 1
            assert jobs[0]["skill_name"] == "briefing"
        finally:
            await mgr.stop()

    async def test_pause_job_sets_enabled_false(self, store, scheduler):
        from scheduler.persistence import get_job_by_id

        await _insert_skill(store, "garmin_stats")
        job_id = await scheduler.add_job("garmin_stats", "0 7 * * *")

        await scheduler.pause_job(job_id)

        record = await get_job_by_id(store, job_id)
        assert record.enabled is False

    async def test_resume_job_sets_enabled_true(self, store, scheduler):
        from scheduler.persistence import get_job_by_id

        await _insert_skill(store, "garmin_stats")
        job_id = await scheduler.add_job("garmin_stats", "0 7 * * *")
        await scheduler.pause_job(job_id)
        await scheduler.resume_job(job_id)

        record = await get_job_by_id(store, job_id)
        assert record.enabled is True

    async def test_delete_job_removes_from_list(self, store, scheduler):
        await _insert_skill(store, "file_monitor")
        job_id = await scheduler.add_job("file_monitor", "0 * * * *")

        await scheduler.delete_job(job_id)

        jobs = scheduler.list_jobs()
        assert all(j["id"] != job_id for j in jobs)

    async def test_delete_job_removes_from_db(self, store, scheduler):
        from scheduler.persistence import get_job_by_id

        await _insert_skill(store, "self_skill")
        job_id = await scheduler.add_job("self_skill", "0 12 * * *")
        await scheduler.delete_job(job_id)

        record = await get_job_by_id(store, job_id)
        assert record is None

    async def test_resolve_job_by_skill_name(self, store, scheduler):
        from errors import SchedulerError

        await _insert_skill(store, "briefing")
        job_id = await scheduler.add_job("briefing", "0 8 * * 1-5")

        # pause_job accepts skill_name string as well as numeric id
        await scheduler.pause_job("briefing")
        from scheduler.persistence import get_job_by_id

        record = await get_job_by_id(store, job_id)
        assert record.enabled is False

    async def test_delete_nonexistent_raises(self, scheduler):
        from errors import SchedulerError

        with pytest.raises(SchedulerError):
            await scheduler.delete_job(9999)

    async def test_pause_nonexistent_raises(self, scheduler):
        from errors import SchedulerError

        with pytest.raises(SchedulerError):
            await scheduler.pause_job(9999)

    async def test_list_jobs_shows_cron_expression(self, store, scheduler):
        await _insert_skill(store, "briefing")
        await scheduler.add_job("briefing", "0 8 * * 1-5")

        jobs = scheduler.list_jobs()
        match = next(j for j in jobs if j["skill_name"] == "briefing")
        assert match["cron_expr"] == "0 8 * * 1-5"
