"""Tests for memory layer: CryptoManager, ContextManager, migrations."""
import pytest


# ---------------------------------------------------------------------------
# CryptoManager
# ---------------------------------------------------------------------------

class TestCryptoManager:
    def test_encrypt_decrypt_roundtrip(self):
        from memory.crypto import CryptoManager

        cm = CryptoManager("test-secret-key-at-least-32chars!")
        data = {"email": "user@example.com", "password": "s3cr3t"}
        blob = cm.encrypt("garmin", data)
        assert isinstance(blob, bytes)
        assert cm.decrypt("garmin", blob) == data

    def test_different_services_use_different_keys(self):
        from memory.crypto import CryptoManager

        cm = CryptoManager("test-secret-key-at-least-32chars!")
        data = {"token": "abc123"}
        blob_a = cm.encrypt("service_a", data)
        blob_b = cm.encrypt("service_b", data)
        # Different salt → different ciphertext
        assert blob_a != blob_b

    def test_wrong_service_cannot_decrypt(self):
        from memory.crypto import CryptoManager

        cm = CryptoManager("test-secret-key-at-least-32chars!")
        blob = cm.encrypt("service_a", {"k": "v"})
        with pytest.raises(Exception):
            cm.decrypt("service_b", blob)

    async def test_save_and_get_credential(self, store):
        from memory.crypto import CryptoManager

        cm = CryptoManager("test-secret-key-at-least-32chars!")
        data = {"api_key": "super_secret_789"}
        await cm.save_credential("myservice", data, store)
        result = await cm.get_credential("myservice", store)
        assert result == data

    async def test_get_credential_returns_none_when_missing(self, store):
        from memory.crypto import CryptoManager

        cm = CryptoManager("test-secret-key-at-least-32chars!")
        result = await cm.get_credential("nonexistent", store)
        assert result is None

    async def test_overwrite_credential(self, store):
        from memory.crypto import CryptoManager

        cm = CryptoManager("test-secret-key-at-least-32chars!")
        await cm.save_credential("svc", {"v": "1"}, store)
        await cm.save_credential("svc", {"v": "2"}, store)
        result = await cm.get_credential("svc", store)
        assert result == {"v": "2"}


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

class TestMigrations:
    async def test_migrations_create_all_tables(self, store):
        rows = await store.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {r["name"] for r in rows}
        for expected in ("messages", "skills", "cron_jobs", "credentials", "file_watches"):
            assert expected in names, f"Table '{expected}' missing"

    async def test_migrations_idempotent(self, tmp_path):
        from memory.store import MemoryStore
        from memory.migrations import run_migrations

        s = MemoryStore(str(tmp_path / "idem.db"))
        await s.init()
        # Running twice must not raise
        await run_migrations(s)
        await run_migrations(s)
        row = await s.fetchone("SELECT MAX(version) AS v FROM schema_version")
        assert row["v"] is not None
        await s.close()

    async def test_schema_version_recorded(self, store):
        row = await store.fetchone("SELECT COUNT(*) AS c FROM schema_version")
        assert row["c"] >= 1


# ---------------------------------------------------------------------------
# ContextManager
# ---------------------------------------------------------------------------

class TestContextManager:
    async def test_add_message_appears_in_context(self, store):
        from llm.context import ContextManager

        ctx = ContextManager(store)
        await ctx.add_message("user", "olá mundo")
        messages = await ctx.get_context()
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "olá mundo"

    async def test_messages_in_chronological_order(self, store):
        from llm.context import ContextManager

        ctx = ContextManager(store)
        await ctx.add_message("user", "first")
        await ctx.add_message("assistant", "second")
        await ctx.add_message("user", "third")
        messages = await ctx.get_context()
        assert [m["content"] for m in messages] == ["first", "second", "third"]

    async def test_context_window_truncation(self, store):
        from llm.context import ContextManager, MAX_CONTEXT_TOKENS, SYSTEM_PROMPT_TOKENS, estimate_tokens

        ctx = ContextManager(store)
        budget = MAX_CONTEXT_TOKENS - SYSTEM_PROMPT_TOKENS

        # Add messages until well over the budget
        large = "x" * 400  # ~100 tokens each
        n = (budget // 100) + 10
        for i in range(n):
            await ctx.add_message("user" if i % 2 == 0 else "assistant", f"msg {i}: {large}")

        messages = await ctx.get_context()

        # Should return fewer messages than we inserted
        assert len(messages) < n
        # Total tokens must fit within the budget
        total = sum(estimate_tokens(m["content"]) for m in messages)
        assert total <= budget

    async def test_clear_removes_all_messages(self, store):
        from llm.context import ContextManager

        ctx = ContextManager(store)
        await ctx.add_message("user", "test")
        await ctx.clear()
        assert await ctx.get_context() == []

    async def test_get_summary_empty(self, store):
        from llm.context import ContextManager

        ctx = ContextManager(store)
        summary = await ctx.get_summary()
        assert "Sem" in summary

    async def test_get_summary_with_messages(self, store):
        from llm.context import ContextManager

        ctx = ContextManager(store)
        await ctx.add_message("user", "hi")
        summary = await ctx.get_summary()
        assert "1" in summary
