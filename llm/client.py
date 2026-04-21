import asyncio
import logging
import time

from openai import AsyncOpenAI, APIConnectionError, APITimeoutError

from config import Config, get_config
from errors import LLMError

logger = logging.getLogger(__name__)

# Wait between retries: 1s, 2s, 4s
_BACKOFF = [1, 2, 4]


class LLMClient:
    def __init__(self, config: Config | None = None):
        cfg = config or get_config()
        self._client = AsyncOpenAI(
            base_url=cfg.lm_studio_base_url,
            api_key="lm-studio",  # LM Studio accepts any non-empty key
            timeout=float(cfg.lm_studio_timeout),
        )
        self._model = cfg.lm_studio_model
        self._max_retries = cfg.max_retries

    async def chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        temperature: float = 0.7,
    ) -> str:
        return await self._request(messages, system_prompt, temperature)

    async def chat_with_code(
        self,
        messages: list[dict[str, str]] | str,
        system_prompt: str | None = None,
    ) -> str:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        return await self._request(messages, system_prompt, temperature=0.2)

    async def is_available(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _request(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None,
        temperature: float,
    ) -> str:
        full_messages: list[dict[str, str]] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                t0 = time.monotonic()
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=full_messages,  # type: ignore[arg-type]
                    temperature=temperature,
                )
                elapsed = time.monotonic() - t0
                total_tokens = response.usage.total_tokens if response.usage else 0
                logger.info(
                    "LLM response in %.2fs (%d tokens)", elapsed, total_tokens
                )
                return response.choices[0].message.content or ""

            except APITimeoutError as exc:
                # APITimeoutError is a subclass of APIConnectionError, so it
                # must be caught first. Timeouts are transient — retry.
                last_exc = exc
                logger.warning(
                    "LLM timeout (tentativa %d/%d)", attempt, self._max_retries
                )

            except APIConnectionError as exc:
                # LM Studio not running. Raise immediately so the bot layer can
                # schedule a retry after 30s (spec section 14).
                raise LLMError(
                    "LM Studio não está acessível. "
                    "Verifica se está a correr em localhost:1234."
                ) from exc

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "LLM error (tentativa %d/%d): %s", attempt, self._max_retries, exc
                )

            if attempt < self._max_retries:
                wait = _BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)]
                logger.debug("Aguardando %ds antes de nova tentativa…", wait)
                await asyncio.sleep(wait)

        raise LLMError(
            f"LLM falhou após {self._max_retries} tentativas."
        ) from last_exc
