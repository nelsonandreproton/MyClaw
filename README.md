# MyClaw

Personal AI assistant that runs locally on your laptop, uses **Telegram** as its interface and **LM Studio** as the LLM backend. All data stays on-device.

---

## Architecture

```
Telegram ──► bot/handlers.py ──► SkillRunner ──► sandbox (exec)
                                      │
                                 LLMClient (LM Studio / OpenAI-compat API)
                                      │
                                 MemoryStore (SQLite + aiosqlite)
                                      │
                         ┌────────────┴────────────┐
                  SchedulerManager            WatchdogManager
                  (APScheduler cron)          (watchdog library)
```

| Layer | What it does |
|---|---|
| `bot/` | Telegram handlers, commands, auth middleware, rate limiting |
| `llm/` | LM Studio client with retry/backoff, sliding-window context, prompt builders |
| `memory/` | Async SQLite store, versioned migrations, Fernet-encrypted credentials |
| `skills/` | AST validator, sandboxed exec, skill runner with LLM-generated code |
| `scheduler/` | APScheduler cron jobs persisted in SQLite |
| `watchdog_manager.py` | File-system watches with debounce and skill triggers |

---

## Requirements

- Python 3.11+
- [LM Studio](https://lmstudio.ai) running locally (default: `http://localhost:1234`)
- A Telegram bot token ([BotFather](https://t.me/BotFather))

---

## Setup

```bash
git clone https://github.com/nelsonandreproton/MyClaw
cd MyClaw
pip install -r requirements.txt
cp .env.example .env   # then edit .env
python main.py
```

### `.env` variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Token from BotFather |
| `TELEGRAM_ALLOWED_USER_ID` | ✅ | — | Your Telegram user ID |
| `SECRET_KEY` | ✅ | — | Master key for credential encryption (min 32 chars) |
| `LM_STUDIO_BASE_URL` | | `http://localhost:1234/v1` | LM Studio API endpoint |
| `LM_STUDIO_MODEL` | | `qwen2.5-coder-14b-instruct` | Model name as shown in LM Studio |
| `LM_STUDIO_TIMEOUT` | | `120` | Request timeout in seconds |
| `ASSISTANT_NAME` | | `Claw` | Name shown in greetings |
| `DB_PATH` | | `./data/assistant.db` | SQLite database path |
| `SKILLS_PATH` | | `./skills` | Directory scanned for `.md` skills |
| `LOG_PATH` | | `./logs` | Directory for rotating log files |
| `LOG_LEVEL` | | `INFO` | Python log level |
| `MAX_RETRIES` | | `3` | LLM retry attempts on timeout |
| `EXECUTION_TIMEOUT` | | `30` | Sandbox execution timeout (seconds) |

---

## Telegram Commands

| Command | Description |
|---|---|
| `/start` | Onboarding — shows available skills |
| `/status` | LM Studio connectivity, uptime, loaded skills |
| `/skills` | List all loaded skills with triggers |
| `/skill <name>` | Run a skill manually |
| `/cron list\|add\|pause\|resume\|delete\|run` | Manage scheduled jobs |
| `/memory clear\|summary` | Manage conversation history |
| `/watch list` | Show active file watches |
| `/logs` | Last 10 log lines |
| `/help` | Command reference |

Any free-form text is routed to the LLM or a matching skill.

---

## Skills

Skills are `.md` files with a YAML frontmatter header and a Python code block. The runner uses the LLM to generate executable code from the skill's description, validates it with an AST checker, and executes it in a restricted sandbox.

### Built-in skills

| Skill | Triggers | Notes |
|---|---|---|
| `briefing` | "bom dia", "briefing" | Morning summary, cron `0 8 * * 1-5` |
| `garmin_stats` | "passos", "sono", "garmin" | Garmin Connect health data |
| `file_monitor` | "monitoriza", "vigia" | Manage file-watch entries |
| `reminder` | "lembra-me", "às Xh" | Create cron-based reminders |
| `self_skill` | "cria skill", "aprende a" | LLM generates and saves new skills |

### Writing a custom skill

```markdown
---
name: my_skill
description: "Does something useful"
version: "1.0.0"
author: "you"
trigger: ["keyword1", "keyword2"]
requires: []
env: []
---

## Código de Referência

```python
# Injected globals available:
#   send_message(text)           — send Telegram message
#   get_credential(service)      — fetch encrypted credential
#   save_credential(service, {}) — store encrypted credential
#   log(message)                 — write to log file
#   user_message                 — original user text

send_message(f"Hello from my_skill! You said: {user_message}")
```
```

Place the file anywhere under `SKILLS_PATH` (e.g. `skills/user/my_skill.md`) and restart or send any message to trigger a reload.

### Sandbox restrictions

Code executing in the sandbox:
- Cannot import `subprocess` or `socket` (blocked at AST and runtime level)
- Cannot call `os.system` or `shutil.rmtree`
- Has call-count limits: `send_message` ≤ 50, credential calls ≤ 10 each
- Times out after `EXECUTION_TIMEOUT` seconds

---

## Scheduler

Cron jobs are backed by APScheduler and persisted in SQLite so they survive restarts. Skills with a `cron:` field in their frontmatter are registered automatically on startup.

```
/cron list
/cron add briefing "0 8 * * 1-5"
/cron pause 1
/cron resume 1
/cron run 1
/cron delete 1
```

---

## File Watching

The WatchdogManager monitors paths registered in the `file_watches` table. When a file changes, it sends a Telegram notification or triggers the associated skill.

```
# Via the file_monitor skill:
monitoriza /var/log/syslog
vigia /home/user/docs/*.log
lista watches
remove watch 2
```

---

## Running Tests

```bash
pytest tests/ -v
```

74 tests covering: memory/crypto, migrations, context manager, LLM client/prompts, skill validator/sandbox/runner, scheduler persistence and manager.

---

## Security Notes

- Credentials (Garmin, API keys) are encrypted with Fernet + PBKDF2-SHA256 (480 000 iterations). The master key is `SECRET_KEY` — use a strong random value (≥ 32 chars).
- The assistant only responds to the single Telegram user ID configured in `TELEGRAM_ALLOWED_USER_ID`.
- LLM-generated code is validated with an AST checker before execution and runs in a restricted namespace. `__import__` is replaced with a runtime guard that enforces the same blocklist.
- Exception details are never forwarded to Telegram; check `/logs` or the log file for diagnostics.
- `SECRET_KEY` and `TELEGRAM_BOT_TOKEN` are redacted from all log output.

---

## Project Layout

```
MyClaw/
├── main.py                  # Async entry point
├── config.py                # Config dataclass + env validation
├── errors.py                # Exception hierarchy
├── watchdog_manager.py      # File-system monitoring
├── requirements.txt
├── pytest.ini
├── bot/
│   ├── handlers.py          # Message handler + Telegram helpers
│   ├── commands.py          # /command handlers
│   └── middleware.py        # Auth + rate limiting
├── llm/
│   ├── client.py            # LM Studio client with retry
│   ├── context.py           # Sliding-window context manager
│   └── prompts.py           # Prompt builders
├── memory/
│   ├── store.py             # Async SQLite wrapper
│   ├── migrations.py        # Versioned schema migrations
│   └── crypto.py            # Fernet credential encryption
├── scheduler/
│   ├── manager.py           # SchedulerManager (APScheduler)
│   ├── jobs.py              # job_executor + builtin cron registration
│   └── persistence.py       # cron_jobs CRUD
├── skills/
│   ├── validator.py         # AST-based code validator
│   ├── sandbox.py           # Restricted exec with timeout
│   ├── runner.py            # SkillRunner: load, match, run
│   └── builtin/             # Built-in skill .md files
└── tests/
    ├── conftest.py
    ├── test_memory.py
    ├── test_llm.py
    ├── test_skills.py
    └── test_scheduler.py
```
