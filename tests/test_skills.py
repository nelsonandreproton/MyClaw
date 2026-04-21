"""Tests for skill validator, sandbox and runner."""
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill_md(tmp_path: Path, name: str, triggers: list, body: str = 'send_message("ok")') -> Path:
    skill_dir = tmp_path / "builtin"
    skill_dir.mkdir(exist_ok=True)
    md = skill_dir / f"{name}.md"
    trigger_yaml = ", ".join(f'"{t}"' for t in triggers)
    md.write_text(
        f"""---
name: {name}
description: "Test skill {name}"
version: "1.0.0"
author: "test"
trigger: [{trigger_yaml}]
requires: []
env: []
---

## Código de Referência

```python
{body}
```
""",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class TestValidator:
    def test_valid_code_passes(self):
        from skills.validator import validate_code

        result = validate_code("x = 1 + 1\nprint(x)")
        assert result.is_valid
        assert result.errors == []

    def test_blocks_subprocess_import(self):
        from skills.validator import validate_code

        result = validate_code("import subprocess\nsubprocess.run(['ls'])")
        assert not result.is_valid
        assert any("subprocess" in e for e in result.errors)

    def test_blocks_socket_import(self):
        from skills.validator import validate_code

        result = validate_code("import socket\ns = socket.socket()")
        assert not result.is_valid
        assert any("socket" in e for e in result.errors)

    def test_blocks_from_subprocess_import(self):
        from skills.validator import validate_code

        result = validate_code("from subprocess import run")
        assert not result.is_valid

    def test_blocks_os_system_call(self):
        from skills.validator import validate_code

        result = validate_code("import os\nos.system('rm -rf /')")
        assert not result.is_valid
        assert any("os.system" in e for e in result.errors)

    def test_blocks_shutil_rmtree(self):
        from skills.validator import validate_code

        result = validate_code("import shutil\nshutil.rmtree('/tmp')")
        assert not result.is_valid
        assert any("shutil.rmtree" in e for e in result.errors)

    def test_allows_json_import(self):
        from skills.validator import validate_code

        result = validate_code("import json\ndata = json.loads('{\"a\": 1}')")
        assert result.is_valid

    def test_allows_os_path(self):
        from skills.validator import validate_code

        result = validate_code("import os\np = os.path.join('/a', 'b')")
        assert result.is_valid

    def test_allows_datetime(self):
        from skills.validator import validate_code

        result = validate_code("from datetime import date\ntoday = date.today()")
        assert result.is_valid

    def test_reports_syntax_error(self):
        from skills.validator import validate_code

        result = validate_code("def broken(\n  pass")
        assert not result.is_valid
        assert any("SyntaxError" in e for e in result.errors)

    def test_reports_line_number(self):
        from skills.validator import validate_code

        result = validate_code("x = 1\nimport subprocess")
        assert not result.is_valid
        assert any("2" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

class TestSandbox:
    def test_output_captured(self):
        from skills.sandbox import execute_in_sandbox

        result = execute_in_sandbox("print('hello world')", {})
        assert result.success
        assert "hello world" in result.output

    def test_multiple_prints_captured(self):
        from skills.sandbox import execute_in_sandbox

        result = execute_in_sandbox("print('a')\nprint('b')\nprint('c')", {})
        assert result.success
        assert "a" in result.output
        assert "c" in result.output

    def test_timeout_returns_error(self):
        import time
        from skills.sandbox import execute_in_sandbox

        t0 = time.monotonic()
        result = execute_in_sandbox("import time\ntime.sleep(60)", {}, timeout=1)
        elapsed = time.monotonic() - t0

        assert not result.success
        assert "Timeout" in (result.error or "")
        assert elapsed < 5  # must return quickly, not block for 60s

    def test_runtime_exception_captured(self):
        from skills.sandbox import execute_in_sandbox

        result = execute_in_sandbox("raise ValueError('test error')", {})
        assert not result.success
        assert "test error" in (result.error or "")

    def test_injected_function_callable(self):
        from skills.sandbox import execute_in_sandbox

        calls = []
        result = execute_in_sandbox(
            "greet('world')",
            {"greet": lambda name: calls.append(name)},
        )
        assert result.success
        assert calls == ["world"]

    def test_injected_variable_accessible(self):
        from skills.sandbox import execute_in_sandbox

        result = execute_in_sandbox("print(user_message)", {"user_message": "test input"})
        assert result.success
        assert "test input" in result.output

    def test_standard_builtins_available(self):
        from skills.sandbox import execute_in_sandbox

        code = "data = [3, 1, 2]\nprint(sorted(data))\nprint(len(data))"
        result = execute_in_sandbox(code, {})
        assert result.success
        assert "[1, 2, 3]" in result.output
        assert "3" in result.output

    def test_output_captured_even_on_timeout(self):
        from skills.sandbox import execute_in_sandbox

        code = "print('before sleep')\nimport time\ntime.sleep(60)"
        result = execute_in_sandbox(code, {}, timeout=1)
        assert not result.success
        # Output up to the timeout should be captured
        assert "before sleep" in result.output


# ---------------------------------------------------------------------------
# parse_skill_md
# ---------------------------------------------------------------------------

class TestParseSkillMd:
    def test_valid_frontmatter_parsed(self, tmp_path):
        from skills.runner import parse_skill_md

        md = tmp_path / "my.md"
        md.write_text(
            """---
name: my_skill
description: "Does something"
version: "2.1.0"
author: "alice"
trigger: ["keyword1", "keyword2"]
requires: ["requests"]
env: ["API_KEY"]
---

## Código

```python
send_message("hello")
```
""",
            encoding="utf-8",
        )

        skill = parse_skill_md(md)
        assert skill.name == "my_skill"
        assert skill.version == "2.1.0"
        assert skill.author == "alice"
        assert "keyword1" in skill.trigger
        assert "requests" in skill.requires
        assert "API_KEY" in skill.env
        assert "send_message" in skill.body

    def test_cron_field_parsed(self, tmp_path):
        from skills.runner import parse_skill_md

        md = tmp_path / "cron_skill.md"
        md.write_text(
            """---
name: cron_skill
description: "Cron test"
version: "1.0.0"
author: "user"
cron: "0 8 * * 1-5"
trigger: []
requires: []
env: []
---

```python
pass
```
""",
            encoding="utf-8",
        )
        skill = parse_skill_md(md)
        assert skill.cron == "0 8 * * 1-5"

    def test_missing_name_raises_valueerror(self, tmp_path):
        from skills.runner import parse_skill_md

        md = tmp_path / "bad.md"
        md.write_text(
            """---
description: "No name field"
trigger: []
---

body
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="name"):
            parse_skill_md(md)

    def test_missing_frontmatter_raises_valueerror(self, tmp_path):
        from skills.runner import parse_skill_md

        md = tmp_path / "no_front.md"
        md.write_text("Just body text, no frontmatter.", encoding="utf-8")
        with pytest.raises(ValueError):
            parse_skill_md(md)


# ---------------------------------------------------------------------------
# SkillRunner
# ---------------------------------------------------------------------------

class TestSkillRunner:
    async def test_load_and_match_by_keyword(self, tmp_path, store):
        from skills.runner import SkillRunner

        skills_root = _make_skill_md(tmp_path, "garmin_stats", ["garmin", "passos", "sono"])
        runner = SkillRunner(str(skills_root), store=store)
        await runner.load()

        assert "garmin_stats" in runner.skills
        matched = runner.match_skill("quantos passos dei hoje?")
        assert matched is not None
        assert matched.name == "garmin_stats"

    async def test_load_multiple_skills(self, tmp_path, store):
        from skills.runner import SkillRunner

        _make_skill_md(tmp_path, "skill_a", ["alpha"])
        _make_skill_md(tmp_path, "skill_b", ["beta"])
        runner = SkillRunner(str(tmp_path), store=store)
        await runner.load()

        assert len(runner.skills) == 2

    async def test_match_returns_none_for_unknown_text(self, tmp_path, store):
        from skills.runner import SkillRunner

        _make_skill_md(tmp_path, "my_skill", ["specific_keyword"])
        runner = SkillRunner(str(tmp_path), store=store)
        await runner.load()

        assert runner.match_skill("olá, bom dia, como estás?") is None

    async def test_match_skill_accent_insensitive(self, tmp_path, store):
        from skills.runner import SkillRunner

        # Trigger without accent: "frequencia cardiaca"
        _make_skill_md(tmp_path, "hr_skill", ["frequencia cardiaca"])
        runner = SkillRunner(str(tmp_path), store=store)
        await runner.load()

        # User types with accents: "frequência cardíaca"
        matched = runner.match_skill("qual a minha frequência cardíaca?")
        assert matched is not None
        assert matched.name == "hr_skill"

    async def test_match_skill_case_insensitive(self, tmp_path, store):
        from skills.runner import SkillRunner

        _make_skill_md(tmp_path, "upper_skill", ["GARMIN"])
        runner = SkillRunner(str(tmp_path), store=store)
        await runner.load()

        matched = runner.match_skill("mostra dados garmin")
        assert matched is not None

    async def test_skills_upserted_to_db(self, tmp_path, store):
        from skills.runner import SkillRunner

        _make_skill_md(tmp_path, "db_skill", ["database"])
        runner = SkillRunner(str(tmp_path), store=store)
        await runner.load()

        row = await store.fetchone("SELECT name FROM skills WHERE name = 'db_skill'")
        assert row is not None
        assert row["name"] == "db_skill"

    async def test_invalid_skill_file_skipped(self, tmp_path, store):
        from skills.runner import SkillRunner

        # Valid skill
        _make_skill_md(tmp_path, "good_skill", ["good"])
        # Invalid skill (no frontmatter)
        bad = tmp_path / "builtin" / "bad.md"
        bad.write_text("no frontmatter here", encoding="utf-8")

        runner = SkillRunner(str(tmp_path), store=store)
        await runner.load()

        # Only the valid skill should be loaded
        assert "good_skill" in runner.skills
        assert len(runner.skills) == 1
