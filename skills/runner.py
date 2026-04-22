from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine

import yaml

from errors import SkillError
from llm.prompts import build_skill_prompt, build_error_retry_prompt
from skills.validator import validate_code
from skills.sandbox import execute_in_sandbox

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SkillDefinition:
    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = "user"
    cron: str | None = None
    trigger: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    env: list[str] = field(default_factory=list)
    body: str = ""
    md_path: str = ""


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def parse_skill_md(path: Path | str) -> SkillDefinition:
    content = Path(path).read_text(encoding="utf-8")

    if not content.startswith("---"):
        raise ValueError(f"Missing YAML frontmatter in {path}")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Malformed frontmatter in {path}")

    _, yaml_block, body = parts
    meta: dict = yaml.safe_load(yaml_block) or {}

    if "name" not in meta:
        raise ValueError(f"Missing required field 'name' in {path}")

    return SkillDefinition(
        name=meta["name"],
        description=meta.get("description", ""),
        version=str(meta.get("version", "1.0.0")),
        author=meta.get("author", "user"),
        cron=str(meta["cron"]) if meta.get("cron") else None,
        trigger=list(meta.get("trigger") or []),
        requires=list(meta.get("requires") or []),
        env=list(meta.get("env") or []),
        body=body.strip(),
        md_path=str(path),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*([\s\S]*?)```")


def _normalize(text: str) -> str:
    """Strip accents for accent-insensitive keyword matching (e.g. 'ola' matches 'olá')."""
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii")


def _extract_code(text: str) -> str | None:
    """Return the first Python code block found in *text*, or None."""
    m = _CODE_BLOCK_RE.search(text)
    if m:
        code = m.group(1).strip()
        return code if code else None
    return None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class SkillRunner:
    def __init__(
        self,
        skills_path: Path | str,
        store: Any = None,
        crypto: Any = None,
        max_retries: int = 3,
        timeout: int = 30,
    ):
        self._path = Path(skills_path)
        self._store = store
        self._crypto = crypto
        self._max_retries = max_retries
        self._timeout = timeout
        self.skills: dict[str, SkillDefinition] = {}

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    async def load(self) -> None:
        self.skills = {}
        if not self._path.exists():
            logger.warning("Skills path does not exist: %s", self._path)
            return

        for md_file in sorted(self._path.rglob("*.md")):
            try:
                skill = parse_skill_md(md_file)
                self.skills[skill.name] = skill
                await self._upsert_db(skill)
                logger.debug("Loaded skill '%s' from %s", skill.name, md_file.name)
            except Exception as exc:
                logger.warning("Skipping %s — %s", md_file, exc)

        logger.info("Loaded %d skill(s)", len(self.skills))

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match_skill(self, text: str) -> SkillDefinition | None:
        text_norm = _normalize(text.lower())
        for skill in self.skills.values():
            if any(_normalize(kw.lower()) in text_norm for kw in skill.trigger):
                return skill
        return None

    # ------------------------------------------------------------------
    # Execution (spec section 6 flow)
    # ------------------------------------------------------------------

    async def run_skill(
        self,
        skill: SkillDefinition,
        user_message: str,
        context_manager: Any,
        llm_client: Any,
        send_fn: Callable[[str], Coroutine],
    ) -> None:
        loop = asyncio.get_running_loop()
        injected = self._make_injected_context(loop, send_fn)

        history = await context_manager.get_context() if context_manager else []
        base_messages = build_skill_prompt(skill.body, user_message, history)

        last_error = ""

        for attempt in range(1, self._max_retries + 1):
            messages = (
                base_messages
                if attempt == 1
                else build_error_retry_prompt(base_messages, last_error, attempt)
            )

            # Step 3: LLM generates code
            try:
                system = messages[0]["content"]
                conv = messages[1:]
                llm_response = await llm_client.chat_with_code(conv, system_prompt=system)
            except Exception as exc:
                last_error = f"LLM error: {exc}"
                logger.warning("Skill '%s' attempt %d — %s", skill.name, attempt, last_error)
                continue

            # Step 4: extract code block
            code = _extract_code(llm_response)
            if not code:
                last_error = "Sem bloco de código na resposta do LLM."
                logger.warning("Skill '%s' attempt %d — no code block", skill.name, attempt)
                continue

            # Step 5: validate
            result_v = validate_code(code)
            if not result_v.is_valid:
                last_error = "Código inválido: " + "; ".join(result_v.errors)
                logger.warning("Skill '%s' attempt %d — %s", skill.name, attempt, last_error)
                continue

            # Step 6: execute in sandbox (off the event loop thread)
            result_e = await loop.run_in_executor(
                None,
                lambda c=code: execute_in_sandbox(c, injected, self._timeout),
            )

            # Step 7a: success
            if result_e.success:
                await self._update_stats(skill.name)
                if result_e.output.strip():
                    await send_fn(result_e.output.strip())
                return

            # Step 7b: error → retry
            last_error = result_e.error or "Execução falhou."
            await self._save_error(skill.name, last_error)
            logger.warning(
                "Skill '%s' attempt %d — execution error: %s", skill.name, attempt, last_error
            )

        # Step 8: all retries exhausted
        await send_fn(
            f"❌ *{skill.name}* falhou após {self._max_retries} tentativas.\n`{last_error}`"
        )

    # ------------------------------------------------------------------
    # Injected context (sync wrappers bridging thread → event loop)
    # ------------------------------------------------------------------

    def _make_injected_context(
        self,
        loop: asyncio.AbstractEventLoop,
        send_fn: Callable,
    ) -> dict:
        _counts: dict[str, int] = {"send_message": 0, "get_credential": 0, "save_credential": 0}
        _MAX_CALLS = {"send_message": 50, "get_credential": 10, "save_credential": 10}
        _MSG_MAX_LEN = 10_000  # characters

        def send_message(text: str) -> None:
            _counts["send_message"] += 1
            if _counts["send_message"] > _MAX_CALLS["send_message"]:
                raise RuntimeError("send_message: call limit exceeded")
            truncated = str(text)[:_MSG_MAX_LEN]
            f = asyncio.run_coroutine_threadsafe(send_fn(truncated), loop)
            f.result(timeout=15)

        def get_credential(service: str) -> dict | None:
            _counts["get_credential"] += 1
            if _counts["get_credential"] > _MAX_CALLS["get_credential"]:
                raise RuntimeError("get_credential: call limit exceeded")
            if not (self._crypto and self._store):
                return None
            f = asyncio.run_coroutine_threadsafe(
                self._crypto.get_credential(service, self._store), loop
            )
            return f.result(timeout=10)

        def save_credential(service: str, data: dict) -> None:
            _counts["save_credential"] += 1
            if _counts["save_credential"] > _MAX_CALLS["save_credential"]:
                raise RuntimeError("save_credential: call limit exceeded")
            if not (self._crypto and self._store):
                return
            f = asyncio.run_coroutine_threadsafe(
                self._crypto.save_credential(service, data, self._store), loop
            )
            f.result(timeout=10)

        def log(message: str) -> None:
            logger.info("[skill] %s", str(message)[:1_000])

        return {
            "send_message": send_message,
            "get_credential": get_credential,
            "save_credential": save_credential,
            "log": log,
        }

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    async def _upsert_db(self, skill: SkillDefinition) -> None:
        if not self._store:
            return
        existing = await self._store.fetchone(
            "SELECT id FROM skills WHERE name = ?", (skill.name,)
        )
        if existing:
            await self._store.execute(
                "UPDATE skills SET description=?, md_path=?, enabled=1 WHERE name=?",
                (skill.description, skill.md_path, skill.name),
            )
        else:
            await self._store.execute(
                "INSERT INTO skills (name, description, md_path) VALUES (?, ?, ?)",
                (skill.name, skill.description, skill.md_path),
            )

    async def _update_stats(self, skill_name: str) -> None:
        if not self._store:
            return
        await self._store.execute(
            "UPDATE skills SET last_run=CURRENT_TIMESTAMP, run_count=run_count+1 WHERE name=?",
            (skill_name,),
        )

    async def _save_error(self, skill_name: str, error: str) -> None:
        if not self._store:
            return
        await self._store.execute(
            "UPDATE skills SET last_error=? WHERE name=?",
            (error, skill_name),
        )
