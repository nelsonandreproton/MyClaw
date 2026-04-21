"""Tests for LLM client, context window and prompt builders."""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config():
    from config import Config

    return Config(
        telegram_bot_token="x",
        telegram_allowed_user_id=12345,
        lm_studio_base_url="http://localhost:1234/v1",
        lm_studio_model="test-model",
        lm_studio_timeout=10,
        assistant_name="TestBot",
        secret_key="test-secret-key-at-least-32chars!",
        db_path=Path("/tmp/test.db"),
        skills_path=Path("/tmp/skills"),
        log_path=Path("/tmp"),
        log_level="DEBUG",
        max_retries=3,
        execution_timeout=5,
    )


def _mock_response(content: str = "resposta do LLM") -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage.total_tokens = 42
    return resp


def _patched_client(response=None, side_effect=None):
    """Return a context manager that patches AsyncOpenAI with a mock instance."""
    mock_instance = MagicMock()
    mock_instance.chat.completions.create = AsyncMock(
        return_value=response, side_effect=side_effect
    )
    return patch("llm.client.AsyncOpenAI", return_value=mock_instance), mock_instance


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------

class TestLLMClient:
    async def test_chat_returns_string(self):
        from llm.client import LLMClient

        ctx, instance = _patched_client(response=_mock_response("hello"))
        with ctx:
            client = LLMClient(_make_config())
            result = await client.chat([{"role": "user", "content": "olá"}])

        assert result == "hello"
        assert isinstance(result, str)

    async def test_chat_with_system_prompt(self):
        from llm.client import LLMClient

        ctx, instance = _patched_client(response=_mock_response("ok"))
        with ctx:
            client = LLMClient(_make_config())
            await client.chat(
                [{"role": "user", "content": "test"}],
                system_prompt="You are a bot.",
            )

        call_args = instance.chat.completions.create.call_args
        msgs = call_args.kwargs.get("messages") or call_args.args[0]
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are a bot."

    async def test_chat_retries_on_timeout_then_raises(self):
        from llm.client import LLMClient
        from errors import LLMError
        import httpx
        from openai import APITimeoutError

        exc = APITimeoutError(request=httpx.Request("POST", "http://localhost:1234"))
        ctx, instance = _patched_client(side_effect=exc)

        with ctx, patch("asyncio.sleep", new_callable=AsyncMock):
            client = LLMClient(_make_config())
            with pytest.raises(LLMError, match="tentativas"):
                await client.chat([{"role": "user", "content": "olá"}])

        assert instance.chat.completions.create.call_count == 3

    async def test_timeout_retries_sleep_between_attempts(self):
        from llm.client import LLMClient
        from errors import LLMError
        import httpx
        from openai import APITimeoutError

        exc = APITimeoutError(request=httpx.Request("POST", "http://localhost:1234"))
        ctx, _ = _patched_client(side_effect=exc)

        with ctx, patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            client = LLMClient(_make_config())
            with pytest.raises(LLMError):
                await client.chat([{"role": "user", "content": "olá"}])

        # max_retries=3 → 2 sleeps between attempts
        assert mock_sleep.call_count == 2

    async def test_connection_error_raises_immediately_no_retry(self):
        from llm.client import LLMClient
        from errors import LLMError
        import httpx
        from openai import APIConnectionError

        exc = APIConnectionError(request=httpx.Request("POST", "http://localhost:1234"))
        ctx, instance = _patched_client(side_effect=exc)

        with ctx:
            client = LLMClient(_make_config())
            with pytest.raises(LLMError, match="LM Studio"):
                await client.chat([{"role": "user", "content": "olá"}])

        # Exactly 1 attempt — connection errors are not retried
        assert instance.chat.completions.create.call_count == 1

    async def test_chat_with_code_uses_low_temperature(self):
        from llm.client import LLMClient

        ctx, instance = _patched_client(response=_mock_response("```python\npass\n```"))
        with ctx:
            client = LLMClient(_make_config())
            await client.chat_with_code([{"role": "user", "content": "code this"}])

        call_args = instance.chat.completions.create.call_args
        temp = call_args.kwargs.get("temperature")
        assert temp == 0.2


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

class TestPromptBuilders:
    def test_system_prompt_contains_current_year(self):
        from llm.prompts import build_system_prompt
        from datetime import datetime

        prompt = build_system_prompt("TestBot", ["skill1"])
        assert str(datetime.now().year) in prompt

    def test_system_prompt_contains_assistant_name(self):
        from llm.prompts import build_system_prompt

        prompt = build_system_prompt("MyClaw", [])
        assert "MyClaw" in prompt

    def test_system_prompt_lists_skills(self):
        from llm.prompts import build_system_prompt

        prompt = build_system_prompt("Bot", ["garmin_stats", "briefing", "reminder"])
        assert "garmin_stats" in prompt
        assert "briefing" in prompt
        assert "reminder" in prompt

    def test_build_skill_prompt_structure(self):
        from llm.prompts import build_skill_prompt

        msgs = build_skill_prompt("skill body", "show steps", [])
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"
        assert "show steps" in msgs[-1]["content"]

    def test_build_skill_prompt_includes_history(self):
        from llm.prompts import build_skill_prompt

        history = [
            {"role": "user", "content": "prev message"},
            {"role": "assistant", "content": "prev reply"},
        ]
        msgs = build_skill_prompt("body", "new request", history)
        contents = [m["content"] for m in msgs]
        assert "prev message" in contents
        assert "new request" in contents

    def test_build_error_retry_prompt_appends_error(self):
        from llm.prompts import build_error_retry_prompt

        original = [{"role": "user", "content": "generate code"}]
        msgs = build_error_retry_prompt(original, "NameError: x not defined", attempt=2)
        last = msgs[-1]["content"]
        assert "NameError" in last
        assert "2" in last

    def test_compression_prompt_includes_conversation(self):
        from llm.prompts import build_compression_prompt

        prompt = build_compression_prompt("user: hi\nassistant: hello")
        assert "user: hi" in prompt
