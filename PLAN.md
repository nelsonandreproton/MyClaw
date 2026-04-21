# MyClaw — Plano de Sessões de Implementação

> Baseado na especificação técnica v1.0 (2026-04-21).
> Stack: Python 3.11+ · LM Studio · Telegram · SQLite

---

## Resumo das Sessões

| # | Sessão | Ficheiros | Estimativa |
|---|--------|-----------|------------|
| 1 | Fundação — Core & Config | 6 ficheiros | ~2h |
| 2 | LLM Client | 3 ficheiros | ~1.5h |
| 3 | Bot Telegram | 4 ficheiros | ~2h |
| 4 | Motor de Skills | 3 ficheiros | ~3h |
| 5 | Scheduler | 3 ficheiros | ~1.5h |
| 6 | Skills Built-in (Markdown) | 5 ficheiros | ~2h |
| 7 | Watchdog | 1 módulo | ~1h |
| 8 | Testes | 4 ficheiros | ~2h |

---

## Sessão 1 — Fundação: Core & Config

**Objetivo**: Infra-estrutura base. Tudo o resto depende disto.

### Ficheiros a criar

```
.env.example
config.py
memory/__init__.py
memory/store.py
memory/migrations.py
memory/crypto.py
```

### Detalhes

#### `.env.example`
Template com todas as variáveis necessárias (sem valores reais):
```
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_ID=
LM_STUDIO_BASE_URL=http://localhost:1234/v1
LM_STUDIO_MODEL=qwen2.5-coder-14b-instruct
LM_STUDIO_TIMEOUT=120
ASSISTANT_NAME=Claw
SECRET_KEY=
DB_PATH=./data/assistant.db
SKILLS_PATH=./skills
LOG_PATH=./logs
LOG_LEVEL=INFO
MAX_RETRIES=3
EXECUTION_TIMEOUT=30
```

#### `config.py`
- Carregar `.env` com `python-dotenv`
- Dataclass/TypedDict `Config` com todos os campos
- Validação na startup (campos obrigatórios presentes)
- Configuração de logging (RotatingFileHandler, max 10MB, 5 ficheiros)
- Singleton `get_config()` thread-safe

#### `memory/store.py`
- Classe `MemoryStore` com `aiosqlite`
- Métodos async: `init()`, `close()`, `execute()`, `fetchone()`, `fetchall()`
- Context manager `async with MemoryStore() as db`
- Pool de conexões (1 conexão por ser SQLite)

#### `memory/migrations.py`
- Função `run_migrations(db)` idempotente
- Criar as 5 tabelas do schema: `messages`, `skills`, `cron_jobs`, `credentials`, `file_watches`
- Versioning de schema (tabela `schema_version`)
- Aplicar apenas migrações pendentes

#### `memory/crypto.py`
- Classe `CryptoManager` usando `cryptography.fernet`
- `encrypt(data: dict) -> bytes` — serializa JSON e encripta
- `decrypt(blob: bytes) -> dict` — desencripta e deserializa
- Chave derivada de `SECRET_KEY` via PBKDF2 + salt fixo por serviço
- `save_credential(service, data)` e `get_credential(service)` usando `MemoryStore`

### Critérios de aceitação
- [ ] `python -c "from config import get_config; print(get_config())"` não falha
- [ ] Tabelas criadas corretamente ao iniciar `MemoryStore`
- [ ] `encrypt(decrypt(data)) == data` para qualquer dict
- [ ] Credencial guardada e recuperada corretamente do SQLite

---

## Sessão 2 — LLM Client

**Objetivo**: Interface com o LM Studio. Sem isto não há geração de código nem respostas.

### Ficheiros a criar

```
llm/__init__.py
llm/client.py
llm/context.py
llm/prompts.py
```

### Detalhes

#### `llm/client.py`
- Classe `LLMClient` com `AsyncOpenAI` (base_url = LM Studio)
- `chat(messages, system_prompt, temperature=0.7) -> str`
- `chat_with_code(prompt) -> str` — temperatura mais baixa (0.2) para geração de código
- Retry automático (até 3x) com backoff exponencial em `LLMError`
- Timeout configurável via `LM_STUDIO_TIMEOUT`
- Detetar se LM Studio está offline e lançar `LLMError` com mensagem clara

#### `llm/context.py`
- Classe `ContextManager` com `MemoryStore`
- `get_context(max_tokens=8192) -> list[dict]` — histórico recente formatado para OpenAI
- Janela deslizante: manter últimas 5 mensagens completas + resumo das anteriores
- `add_message(role, content, skill_name=None)` — persiste em SQLite
- `compress_history()` — resume mensagens antigas via LLM ("resume em 3 frases")
- Estimativa de tokens: `estimate_tokens(text) -> int` (aprox: `len(text) // 4`)
- Constantes: `MAX_CONTEXT_TOKENS=8192`, `MAX_HISTORY_MESSAGES=20`, `SYSTEM_PROMPT_TOKENS=1024`, `SKILL_CONTEXT_TOKENS=2048`

#### `llm/prompts.py`
- `build_system_prompt(config, skills_list) -> str` — injeta datetime e lista de skills
- `build_skill_prompt(skill_md_content, user_request, history) -> list[dict]`
- `build_error_retry_prompt(original_prompt, error, attempt) -> list[dict]`
- `build_compression_prompt(messages) -> str`
- Template base do system prompt conforme spec (seção 9)

### Critérios de aceitação
- [ ] `LLMClient.chat([{"role":"user","content":"ping"}])` retorna string (com LM Studio a correr)
- [ ] `ContextManager` guarda e recupera mensagens do SQLite
- [ ] Contexto não excede `MAX_CONTEXT_TOKENS` mesmo com histórico longo
- [ ] Retry automático em caso de timeout

---

## Sessão 3 — Bot Telegram

**Objetivo**: Interface com o utilizador. Liga tudo o resto ao Telegram.

### Ficheiros a criar

```
bot/__init__.py
bot/middleware.py
bot/handlers.py
bot/commands.py
main.py
```

### Detalhes

#### `bot/middleware.py`
- `auth_middleware(update, context)` — verifica `TELEGRAM_ALLOWED_USER_ID`
- Rejeitar silenciosamente mensagens de outros utilizadores
- Log de tentativas não autorizadas (user_id + timestamp)
- Rate limiting: max 10 mensagens por minuto por utilizador

#### `bot/handlers.py`
- `message_handler(update, context)` — handler principal de texto livre
- Fluxo: verificar auth → identificar skill por keywords → executar skill OU responder conversacionalmente
- Tipagem com `ContextTypes.DEFAULT_TYPE`
- Enviar "a processar..." enquanto espera resposta do LLM
- Suporte a mensagens longas (split em chunks de 4096 chars, limite Telegram)

#### `bot/commands.py`
- `/start` — onboarding (ver Sessão fluxo abaixo)
- `/status` — LLM online?, jobs ativos, skills carregadas, uptime
- `/skills` — lista todas as skills (nome + descrição)
- `/skill <nome>` — executa skill manualmente
- `/skill new` — cria nova skill interativamente
- `/cron list|pause|resume|delete|run|add` — gestão de cron jobs
- `/memory` — resumo do contexto atual
- `/memory clear` — limpar histórico
- `/watch list` — ficheiros monitorizados
- `/logs` — últimas 10 linhas de log
- `/help` — ajuda completa

**Fluxo de onboarding** (`/start` na primeira execução):
1. Verificar se tabela `messages` está vazia
2. Pedir nome do assistente (ou usar `ASSISTANT_NAME` do env)
3. Apresentar skills disponíveis com botões inline (briefing, garmin, monitor, reminder)
4. Para cada skill selecionada, pedir credenciais necessárias
5. Confirmar configuração e agendar cron jobs
6. Guardar perfil, enviar mensagem de boas-vindas

#### `main.py`
- Inicialização pela ordem: Config → DB + Migrations → CryptoManager → SchedulerManager → WatchdogManager → Bot
- `Application.builder().token(...).build()`
- Registar handlers e commands
- Graceful shutdown: capturar `SIGINT`/`SIGTERM`, fechar DB, parar scheduler, parar watchdog
- Entry point: `if __name__ == "__main__": asyncio.run(main())`

### Critérios de aceitação
- [ ] Bot inicia sem erros com `.env` válido
- [ ] Mensagem de utilizador não autorizado é silenciada
- [ ] `/status` responde com estado correto
- [ ] `/help` lista todos os comandos
- [ ] Onboarding flui sem erros na primeira execução

---

## Sessão 4 — Motor de Skills

**Objetivo**: O coração do assistente. Parser de Markdown → execução sandboxada com retry automático.

### Ficheiros a criar

```
skills/__init__.py
skills/validator.py
skills/sandbox.py
skills/runner.py
```

### Detalhes

#### `skills/validator.py`
- `validate_code(code: str) -> ValidationResult`
- Parse AST com `ast.parse()`
- Verificar imports contra `BLOCKED_IMPORTS`: `subprocess`, `os.system`, `shutil.rmtree`, `socket`, `__import__`
- Verificar builtins usados contra `ALLOWED_BUILTINS`
- Retornar erros específicos (qual import, qual linha)
- `ValidationResult` com `is_valid: bool`, `errors: list[str]`

#### `skills/sandbox.py`
- `execute_in_sandbox(code: str, injected_context: dict, timeout: int) -> ExecutionResult`
- Executar em thread separada via `concurrent.futures.ThreadPoolExecutor`
- Timeout via `future.result(timeout=EXECUTION_TIMEOUT)`
- Namespace de execução restrito: só `ALLOWED_BUILTINS` + `injected_context`
- Capturar stdout (redirect `sys.stdout`) para incluir no resultado
- `ExecutionResult` com `success: bool`, `output: str`, `error: str | None`

#### `skills/runner.py`
- `parse_skill_md(path: str) -> SkillDefinition` — extrai frontmatter YAML + corpo Markdown
- `SkillDefinition`: dataclass com `name`, `description`, `version`, `author`, `cron`, `trigger`, `requires`, `env`, `body`
- `load_all_skills(skills_path: str) -> dict[str, SkillDefinition]`
- `match_skill(message: str, skills: dict) -> SkillDefinition | None` — por keywords em `trigger`
- `run_skill(skill, user_message, context_manager, llm_client, send_fn) -> str`

**Fluxo `run_skill`** (conforme spec seção 6):
```
1. Ler .md da skill
2. Construir prompt: system + skill .md + pedido do utilizador + histórico
3. LLM gera código Python
4. Extrair bloco ```python ... ``` da resposta
5. validate_code() — se inválido, retry com erro
6. execute_in_sandbox() com contexto injetado:
   - send_message(text)
   - get_credential(service)
   - save_credential(service, data)
   - log(message)
7a. Sucesso → output para Telegram, update SQLite (last_run, run_count)
7b. Erro → voltar ao passo 2 com erro (até MAX_RETRIES=3)
8. Se 3 falhas → notificar utilizador + guardar last_error em SQLite
```

### Critérios de aceitação
- [ ] `validate_code("import subprocess")` retorna `is_valid=False`
- [ ] `validate_code("import json\nprint('ok')")` retorna `is_valid=True`
- [ ] Sandbox mata execução após timeout
- [ ] `parse_skill_md` extrai corretamente frontmatter YAML
- [ ] Retry automático em caso de erro (até 3x)
- [ ] `send_message` injetado chega ao Telegram

---

## Sessão 5 — Scheduler

**Objetivo**: Cron jobs persistidos que sobrevivem a restarts.

### Ficheiros a criar

```
scheduler/__init__.py
scheduler/persistence.py
scheduler/manager.py
scheduler/jobs.py
```

### Detalhes

#### `scheduler/persistence.py`
- `load_jobs_from_db(db) -> list[JobRecord]`
- `save_job(db, skill_name, cron_expr) -> int`
- `update_job_last_run(db, job_id)`
- `update_job_next_run(db, job_id, next_run)`
- `set_job_enabled(db, job_id, enabled: bool)`
- `delete_job(db, job_id)`

#### `scheduler/manager.py`
- Classe `SchedulerManager` com `AsyncIOScheduler` (APScheduler)
- `start()` — inicia scheduler, carrega jobs do SQLite, regista skills com campo `cron`
- `stop()` — graceful shutdown
- `add_job(skill_name, cron_expr) -> int` — persiste + adiciona ao scheduler
- `pause_job(job_id)`, `resume_job(job_id)`, `delete_job(job_id)`
- `run_now(job_id)` — execução imediata fora do agendamento
- `list_jobs() -> list[JobRecord]`

#### `scheduler/jobs.py`
- `register_builtin_cron_jobs(manager, skills)` — percorre skills com campo `cron` e regista
- `job_executor(skill_name, runner, send_fn)` — função chamada pelo APScheduler
- Tratamento de erros: se job falha, `SchedulerError`, notifica utilizador, não para o scheduler

### Critérios de aceitação
- [ ] Job criado em SQLite sobrevive a restart do processo
- [ ] Skill com `cron: "0 8 * * *"` é registada automaticamente no startup
- [ ] `/cron list` mostra jobs corretos com próxima execução
- [ ] `/cron pause <nome>` pausa sem apagar do SQLite

---

## Sessão 6 — Skills Built-in (Markdown)

**Objetivo**: Os 5 ficheiros `.md` que definem as skills incluídas por defeito.

### Ficheiros a criar

```
skills/builtin/briefing.md
skills/builtin/garmin.md
skills/builtin/monitor.md
skills/builtin/reminder.md
skills/builtin/self_skill.md
```

### Detalhes

#### `briefing.md`
- **Cron**: `0 8 * * 1-5`
- **Conteúdo**: resumo do dia, tarefas pendentes da memória, eventos
- **Código de referência**: ler últimas mensagens do SQLite, formatar resumo

#### `garmin.md`
- **Trigger**: `["garmin", "corrida", "sono", "passos", "frequência cardíaca", "stress", "body battery"]`
- **Auth**: `get_credential("garmin")` — pedir na primeira execução se ausente
- **Código de referência**: conforme spec (seção 5)
- **Output**: Markdown formatado para Telegram com emojis

#### `monitor.md`
- **Trigger**: `["monitoriza", "vigia", "watch", "avisa quando"]`
- **Funcionalidade**: criar entrada em `file_watches` via `save_credential`-like helper
- **Output**: confirmação de monitorização ativa

#### `reminder.md`
- **Trigger**: `["lembra-me", "reminder", "daqui a", "em X minutos", "às HH:MM"]`
- **Funcionalidade**: parsear tempo da mensagem, criar one-shot cron job via APScheduler
- **Código de referência**: parsear "30 minutos" ou "às 22:00", criar job

#### `self_skill.md`
- **Trigger**: `["cria uma skill", "integra com", "adiciona uma skill", "nova skill"]`
- **Fluxo**:
  1. LLM gera ficheiro `.md` completo com frontmatter correto
  2. Mostrar preview ao utilizador
  3. Aguardar confirmação ("sim" / "não")
  4. Se confirmado: guardar em `skills/`, registar em SQLite, recarregar skills
- **Output**: confirmação + nome da skill criada

### Critérios de aceitação
- [ ] `parse_skill_md` lê os 5 ficheiros sem erro
- [ ] Triggers corretos detetados para cada skill
- [ ] `briefing.md` tem cron expression válida
- [ ] `self_skill.md` pede confirmação antes de guardar

---

## Sessão 7 — Watchdog

**Objetivo**: Monitorização de ficheiros em background, trigger de skills.

### Ficheiros a criar

```
# Integrado em main.py e skills/builtin/monitor.md
# Lógica em:
watchdog_manager.py   (módulo raiz, ou dentro de um subpackage)
```

### Detalhes

#### Classe `WatchdogManager`
- Usar biblioteca `watchdog` com `Observer` + `PatternMatchingEventHandler`
- `start()` — carrega `file_watches` do SQLite, regista observers
- `stop()` — para todos os observers
- `add_watch(path, pattern, skill_name)` — adiciona ao SQLite + observer em runtime
- `remove_watch(watch_id)` — para observer e remove do SQLite

#### Handler de eventos
- Eventos suportados: `created`, `modified`, `deleted`, `moved`
- Ao detetar evento: chamar `SkillRunner.run_skill(skill_name, event_info)`
- `event_info` inclui: path, event_type, timestamp
- Debounce de 1s para evitar eventos duplicados (ficheiros grandes)

### Critérios de aceitação
- [ ] Criar ficheiro numa pasta monitorizada dispara notificação Telegram
- [ ] Observer para após `remove_watch()`
- [ ] Watches persistem entre restarts

---

## Sessão 8 — Testes

**Objetivo**: Suite de testes unitários cobrindo os módulos críticos.

### Ficheiros a criar

```
tests/__init__.py
tests/test_llm.py
tests/test_skills.py
tests/test_scheduler.py
tests/test_memory.py
```

### Detalhes

#### `test_llm.py`
- Mock do LM Studio com `unittest.mock.AsyncMock`
- `test_chat_returns_string` — resposta normal
- `test_chat_retries_on_timeout` — verifica 3 tentativas
- `test_context_window_truncation` — histórico longo é truncado
- `test_system_prompt_contains_datetime` — datetime injetado

#### `test_skills.py`
- `test_parse_skill_md_valid` — frontmatter correto extraído
- `test_parse_skill_md_missing_fields` — erro claro em campos obrigatórios
- `test_validator_blocks_subprocess` — `import subprocess` rejeitado
- `test_validator_allows_json` — `import json` permitido
- `test_sandbox_timeout` — código com `time.sleep(60)` é cancelado
- `test_sandbox_output_captured` — `print("ok")` capturado no resultado
- `test_match_skill_by_keyword` — "garmin" activa `garmin_stats`

#### `test_scheduler.py`
- `test_add_job_persists_to_db` — job gravado no SQLite
- `test_load_jobs_on_startup` — jobs recarregados após "restart" (nova instância)
- `test_pause_resume_job` — estado `enabled` atualizado
- `test_delete_job` — removido do SQLite e do scheduler

#### `test_memory.py`
- `test_encrypt_decrypt_roundtrip` — `encrypt(decrypt(x)) == x`
- `test_credential_save_and_get` — CRUD completo
- `test_migrations_idempotent` — correr migrações 2x não falha
- `test_add_message_and_get_context` — mensagem guardada aparece no contexto

### Como correr

```bash
pytest tests/ -v
pytest tests/test_skills.py -v --tb=short
```

### Critérios de aceitação
- [ ] `pytest tests/ -v` passa sem erros
- [ ] Coverage > 70% nos módulos críticos (validator, crypto, context)

---

## Dependências entre Sessões

```
Sessão 1 (Core)
    ↓
Sessão 2 (LLM)  ←── precisa de MemoryStore (Sessão 1)
    ↓
Sessão 4 (Skills) ←── precisa de LLMClient (Sessão 2) + MemoryStore (Sessão 1)
    ↓
Sessão 3 (Bot) ←── precisa de tudo (Sessões 1, 2, 4)
    ↓
Sessão 5 (Scheduler) ←── pode ser paralela com Sessão 3
    ↓
Sessão 6 (Skills .md) ←── precisa do runner funcional (Sessão 4)
    ↓
Sessão 7 (Watchdog) ←── precisa do runner + DB (Sessões 1, 4)
    ↓
Sessão 8 (Testes) ←── testa tudo, precisa de todas as sessões
```

---

## Notas Globais de Implementação

1. **Async everywhere**: todo o código usa `async/await`. Nunca bloquear o event loop.
2. **Error hierarchy**: sempre lançar subclasses de `AssistantError` (ver spec seção 14).
3. **Logging**: usar `logging.getLogger(__name__)` em cada módulo. Nunca `print()` em produção.
4. **Secrets**: `.env` nunca commitado. Validar presença de `SECRET_KEY` no startup.
5. **Imports**: não usar `from x import *`. Imports explícitos sempre.
6. **Type hints**: todos os métodos públicos com type hints completos.
7. **SQLite**: usar sempre `aiosqlite` com `async with`. Nunca sqlite3 síncrono.

---

*Plano gerado em 2026-04-21 — MyClaw v1.0*
