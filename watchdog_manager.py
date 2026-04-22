from __future__ import annotations

import asyncio
import fnmatch
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from memory.store import MemoryStore

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 1.0

_EVENT_LABELS: dict[str, str] = {
    "modified": "modificado",
    "created": "criado",
    "deleted": "eliminado",
    "moved": "movido",
}


class _ChangeHandler(FileSystemEventHandler):
    """Handles filesystem events for a single watch entry."""

    def __init__(
        self,
        watch_id: int,
        path: str,
        pattern: str | None,
        skill_name: str | None,
        manager: "WatchdogManager",
    ) -> None:
        super().__init__()
        self._watch_id = watch_id
        self._path = path
        self._pattern = pattern
        self._skill_name = skill_name
        self._manager = manager
        self._last_event: dict[str, float] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # watchdog callbacks — run in the Observer thread
    # ------------------------------------------------------------------

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._dispatch("modified", str(event.src_path))

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._dispatch("created", str(event.src_path))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._dispatch("deleted", str(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            dest = getattr(event, "dest_path", "")
            self._dispatch("moved", str(event.src_path), str(dest))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _dispatch(self, event_type: str, src_path: str, dest_path: str = "") -> None:
        # Pattern filter
        if self._pattern and not fnmatch.fnmatch(Path(src_path).name, self._pattern):
            return

        # Debounce — per source path
        now = time.monotonic()
        with self._lock:
            if now - self._last_event.get(src_path, 0.0) < _DEBOUNCE_SECONDS:
                return
            self._last_event[src_path] = now

        send_fn = self._manager.send_fn
        loop = self._manager._loop
        if not send_fn or not loop:
            return

        label = _EVENT_LABELS.get(event_type, event_type)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self._skill_name:
            self._trigger_skill(src_path, event_type, label, dest_path, ts, loop)
        else:
            display = f"{src_path} → {dest_path}" if dest_path else src_path
            text = f"👁️ *Ficheiro {label}*\n`{display}`\n_{ts}_"
            try:
                asyncio.run_coroutine_threadsafe(send_fn(text), loop)
            except RuntimeError:
                logger.warning("WatchdogManager: loop closed, dropping event for %s", src_path)

    def _trigger_skill(
        self,
        src_path: str,
        event_type: str,
        label: str,
        dest_path: str,
        ts: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        runner = self._manager.skill_runner
        llm_client = self._manager.llm_client
        send_fn = self._manager.send_fn
        skill_name = self._skill_name

        if not runner or not llm_client or not send_fn:
            logger.warning(
                "WatchdogManager: skill_runner/llm_client/send_fn not set, "
                "cannot trigger skill '%s'",
                skill_name,
            )
            return

        skill = runner.skills.get(skill_name)
        if not skill:
            logger.warning("WatchdogManager: skill '%s' not found, sending plain notification", skill_name)
            display = f"{src_path} → {dest_path}" if dest_path else src_path
            text = f"👁️ *Ficheiro {label}*\n`{display}`\n_{ts}_"
            try:
                asyncio.run_coroutine_threadsafe(send_fn(text), loop)
            except RuntimeError:
                pass
            return

        event_msg = (
            f"Evento de ficheiro detectado:\n"
            f"- Tipo: {event_type}\n"
            f"- Ficheiro: {src_path}"
            + (f"\n- Destino: {dest_path}" if dest_path else "")
            + f"\n- Timestamp: {ts}"
        )

        async def _run() -> None:
            try:
                await runner.run_skill(skill, event_msg, None, llm_client, send_fn)
            except Exception as exc:
                logger.error("WatchdogManager: skill '%s' error: %s", skill_name, exc)

        try:
            asyncio.run_coroutine_threadsafe(_run(), loop)
        except RuntimeError:
            logger.warning("WatchdogManager: loop closed, cannot trigger skill '%s'", skill_name)


class WatchdogManager:
    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self._observer: Observer | None = None
        self._watches: dict[int, Any] = {}           # db_id → ObservedWatch
        self._handlers: dict[int, _ChangeHandler] = {}
        self._rows: list[dict[str, Any]] = []        # snapshot for list_watches()
        self._rows_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

        # Set by main.py after construction
        self.send_fn: Callable[[str], Coroutine] | None = None
        self.skill_runner: Any = None
        self.llm_client: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._observer = Observer()
        self._observer.start()

        rows = await self._store.fetchall(
            "SELECT id, path, pattern, skill_name, enabled "
            "FROM file_watches WHERE enabled = 1"
        )
        for row in rows:
            self._register(
                int(row["id"]),
                str(row["path"]),
                row["pattern"],
                row["skill_name"],
            )

        await self._refresh_rows()
        logger.info("WatchdogManager started — %d watch(es) loaded", len(rows))

    async def stop(self) -> None:
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join(timeout=5)
        self._observer = None
        logger.info("WatchdogManager stopped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_watches(self) -> list[dict[str, Any]]:
        """Synchronous snapshot — used by bot/commands.py."""
        with self._rows_lock:
            return list(self._rows)

    async def add_watch(
        self,
        path: str,
        pattern: str | None = None,
        skill_name: str | None = None,
    ) -> int:
        resolved = Path(path).resolve()
        if not resolved.exists():
            raise ValueError(f"Path does not exist: {path}")
        if resolved.is_symlink():
            raise ValueError(f"Symlinks are not allowed: {path}")
        path = str(resolved)  # store the canonical form

        cursor = await self._store.execute(
            "INSERT INTO file_watches (path, pattern, skill_name, enabled) "
            "VALUES (?, ?, ?, 1)",
            (path, pattern, skill_name),
        )
        watch_id = int(cursor.lastrowid)
        self._register(watch_id, path, pattern, skill_name)
        await self._refresh_rows()
        logger.info(
            "Added watch id=%d path='%s' pattern=%r skill=%r",
            watch_id, path, pattern, skill_name,
        )
        return watch_id

    async def remove_watch(self, watch_id: int) -> None:
        self._unregister(watch_id)
        await self._store.execute("DELETE FROM file_watches WHERE id = ?", (watch_id,))
        await self._refresh_rows()
        logger.info("Removed watch id=%d", watch_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _register(
        self,
        watch_id: int,
        path: str,
        pattern: str | None,
        skill_name: str | None,
    ) -> None:
        if not self._observer:
            return

        handler = _ChangeHandler(watch_id, path, pattern, skill_name, self)
        try:
            obs_watch = self._observer.schedule(handler, path=path, recursive=False)
        except Exception as exc:
            logger.warning("WatchdogManager: cannot watch '%s': %s", path, exc)
            return

        with self._rows_lock:
            self._watches[watch_id] = obs_watch
            self._handlers[watch_id] = handler

    def _unregister(self, watch_id: int) -> None:
        with self._rows_lock:
            obs_watch = self._watches.pop(watch_id, None)
            self._handlers.pop(watch_id, None)
        if obs_watch and self._observer:
            try:
                self._observer.unschedule(obs_watch)
            except Exception as exc:
                logger.warning(
                    "WatchdogManager: failed to unschedule id=%d: %s", watch_id, exc
                )

    async def _refresh_rows(self) -> None:
        rows = await self._store.fetchall(
            "SELECT id, path, pattern, skill_name, enabled "
            "FROM file_watches ORDER BY id"
        )
        with self._rows_lock:
            self._rows = [
                {k: row[k] for k in row.keys()} for row in rows
            ]
