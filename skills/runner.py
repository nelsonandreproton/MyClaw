from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SkillDefinition:
    """Stub — full implementation in Session 4."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.trigger: list[str] = []
        self.cron: str | None = None


class SkillRunner:
    """Stub — full implementation in Session 4."""

    def __init__(self, skills_path: Path | str):
        self._path = Path(skills_path)
        self.skills: dict[str, SkillDefinition] = {}

    async def load(self) -> None:
        logger.debug("SkillRunner.load() — stub")

    def match_skill(self, text: str) -> SkillDefinition | None:
        return None

    async def run_skill(
        self,
        skill: SkillDefinition,
        user_message: str,
        context_manager: Any,
        llm_client: Any,
        send_fn: Any,
    ) -> None:
        logger.debug("SkillRunner.run_skill() — stub")
