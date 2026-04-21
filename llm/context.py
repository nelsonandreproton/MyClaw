import logging
from typing import TYPE_CHECKING

from memory.store import MemoryStore
from errors import LLMError

if TYPE_CHECKING:
    from llm.client import LLMClient

logger = logging.getLogger(__name__)

MAX_CONTEXT_TOKENS = 8192
MAX_HISTORY_MESSAGES = 20
SYSTEM_PROMPT_TOKENS = 1024
SKILL_CONTEXT_TOKENS = 2048
_KEEP_RECENT = 5  # always keep the N most recent messages when compressing


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ContextManager:
    def __init__(self, store: MemoryStore):
        self._store = store

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def add_message(
        self,
        role: str,
        content: str,
        skill_name: str | None = None,
    ) -> None:
        tokens = estimate_tokens(content)
        await self._store.execute(
            "INSERT INTO messages (role, content, tokens, skill_name) VALUES (?, ?, ?, ?)",
            (role, content, tokens, skill_name),
        )

    async def clear(self) -> None:
        await self._store.execute("DELETE FROM messages")
        logger.info("Message history cleared")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_context(
        self,
        max_tokens: int = MAX_CONTEXT_TOKENS,
        reserved_tokens: int = SYSTEM_PROMPT_TOKENS,
    ) -> list[dict[str, str]]:
        """Return recent messages that fit within the token budget.

        Iterates from newest to oldest, collecting messages until the
        available token budget is exhausted, then returns them in
        chronological order for the OpenAI API.
        """
        available = max_tokens - reserved_tokens
        rows = await self._store.fetchall(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
            (MAX_HISTORY_MESSAGES,),
        )

        selected: list[dict[str, str]] = []
        total = 0
        for row in rows:  # newest → oldest
            cost = estimate_tokens(row["content"])
            if total + cost > available:
                break
            selected.append({"role": row["role"], "content": row["content"]})
            total += cost

        selected.reverse()  # chronological order for the API
        return selected

    async def get_summary(self) -> str:
        row = await self._store.fetchone(
            "SELECT COUNT(*) AS total, MIN(created_at) AS since FROM messages"
        )
        if not row or row["total"] == 0:
            return "Sem histórico de conversa."
        return f"{row['total']} mensagens desde {row['since']}."

    # ------------------------------------------------------------------
    # Compression
    # ------------------------------------------------------------------

    async def compress_history(self, llm_client: "LLMClient") -> None:
        """Summarise all but the most recent messages, replacing them with a
        single system-role summary entry."""
        rows = await self._store.fetchall(
            "SELECT id, role, content FROM messages ORDER BY id ASC"
        )
        if len(rows) <= _KEEP_RECENT:
            return

        to_compress = rows[:-_KEEP_RECENT]
        conversation = "\n".join(
            f"{r['role']}: {r['content']}" for r in to_compress
        )

        from llm.prompts import build_compression_prompt  # late import avoids cycle

        prompt = build_compression_prompt(conversation)
        try:
            summary = await llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
            )
        except LLMError:
            logger.warning("Compression failed — keeping original messages")
            return

        ids = tuple(r["id"] for r in to_compress)
        placeholders = ",".join("?" * len(ids))
        await self._store.execute(
            f"DELETE FROM messages WHERE id IN ({placeholders})", ids
        )
        await self.add_message(
            "system", f"[Resumo de conversa anterior]\n{summary}"
        )
        logger.info("Compressed %d messages into a summary", len(to_compress))
