import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.middleware import is_authorized
from bot.handlers import _send_md, _split

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# /start — onboarding on first run, greeting otherwise
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    ctx_manager = context.application.bot_data.get("context_manager")
    config = context.application.bot_data.get("config")
    name = config.assistant_name if config else "Claw"

    is_first_run = True
    if ctx_manager:
        row = await ctx_manager._store.fetchone(
            "SELECT COUNT(*) AS c FROM messages"
        )
        is_first_run = (row["c"] == 0) if row else True

    if is_first_run:
        await _onboarding(update, context, name)
    else:
        await update.message.reply_text(
            f"👋 Olá! Sou o *{name}*. Como posso ajudar?\n\n"
            "Usa /help para ver todos os comandos disponíveis.",
            parse_mode="Markdown",
        )


async def _onboarding(
    update: Update, context: ContextTypes.DEFAULT_TYPE, name: str
) -> None:
    await update.message.reply_text(
        f"👋 Olá! Sou o *{name}*, o teu assistente pessoal local.\n\n"
        "Corro no teu portátil, os teus dados ficam apenas aqui.\n\n"
        "Que skills queres ativar?",
        parse_mode="Markdown",
    )
    keyboard = [
        [
            InlineKeyboardButton("📋 Briefing diário", callback_data="skill_briefing"),
            InlineKeyboardButton("🏃 Garmin Connect", callback_data="skill_garmin"),
        ],
        [
            InlineKeyboardButton("📁 Monitorização ficheiros", callback_data="skill_monitor"),
            InlineKeyboardButton("⏰ Lembretes", callback_data="skill_reminder"),
        ],
        [InlineKeyboardButton("✅ Continuar sem skills extras", callback_data="skill_none")],
    ]
    await update.message.reply_text(
        "Seleciona as skills que queres ativar:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_onboarding_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    choice = query.data  # e.g. "skill_garmin"
    skill_name = choice.removeprefix("skill_")

    if skill_name == "none":
        config = context.application.bot_data.get("config")
        name = config.assistant_name if config else "Claw"
        await query.edit_message_text(
            f"✅ Configuração completa!\n\n"
            f"Estou pronto, *{name}* ao teu serviço.\n"
            "Fala comigo em linguagem natural ou usa /help.",
            parse_mode="Markdown",
        )
        return

    labels = {
        "briefing": "📋 Briefing diário",
        "garmin": "🏃 Garmin Connect",
        "monitor": "📁 Monitorização de ficheiros",
        "reminder": "⏰ Lembretes",
    }
    label = labels.get(skill_name, skill_name)

    await query.edit_message_text(
        f"✅ *{label}* ativada!\n\n"
        "Podes ativar mais skills com /skills ou começar a conversar.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    bot_data = context.application.bot_data
    llm_client = bot_data.get("llm_client")
    skill_runner = bot_data.get("skill_runner")
    scheduler = bot_data.get("scheduler")
    start_time = bot_data.get("start_time")

    llm_ok = await llm_client.is_available() if llm_client else False
    llm_status = "🟢 Online" if llm_ok else "🔴 Offline"

    skills_count = len(skill_runner.skills) if skill_runner else 0

    jobs = scheduler.list_jobs() if scheduler else []
    active_jobs = sum(1 for j in jobs if j.get("enabled", True))

    uptime = "n/d"
    if start_time:
        elapsed = int(time.monotonic() - start_time)
        h, m = divmod(elapsed // 60, 60)
        uptime = f"{h}h {m}m" if h else f"{m}m {elapsed % 60}s"

    await update.message.reply_text(
        f"*Estado do Sistema*\n\n"
        f"🤖 LLM: {llm_status}\n"
        f"🧩 Skills: {skills_count} carregadas\n"
        f"⏰ Cron jobs: {active_jobs} ativos\n"
        f"⏱ Uptime: {uptime}",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /skills
# ---------------------------------------------------------------------------

async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    skill_runner = context.application.bot_data.get("skill_runner")

    if not skill_runner or not skill_runner.skills:
        await update.message.reply_text("Nenhuma skill carregada.")
        return

    lines = ["*Skills disponíveis:*\n"]
    for name, skill in skill_runner.skills.items():
        desc = skill.description or "sem descrição"
        cron = f" _(cron: `{skill.cron}`)_" if skill.cron else ""
        lines.append(f"• *{name}* — {desc}{cron}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /skill [nome | new]
# ---------------------------------------------------------------------------

async def cmd_skill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    args = context.args or []

    if not args:
        await update.message.reply_text(
            "Uso:\n"
            "  /skill <nome> — executa uma skill\n"
            "  /skill new — cria nova skill com o LLM"
        )
        return

    if args[0] == "new":
        await update.message.reply_text(
            "Para criar uma nova skill, descreve o que ela deve fazer.\n\n"
            "_Exemplo: «cria uma skill que mostra o tempo em Lisboa»_",
            parse_mode="Markdown",
        )
        return

    skill_name = args[0]
    skill_runner = context.application.bot_data.get("skill_runner")

    if not skill_runner:
        await update.message.reply_text("Motor de skills não disponível ainda.")
        return

    skill = skill_runner.skills.get(skill_name)
    if not skill:
        available = ", ".join(skill_runner.skills.keys()) or "nenhuma"
        await update.message.reply_text(
            f"Skill *{skill_name}* não encontrada.\nDisponíveis: {available}",
            parse_mode="Markdown",
        )
        return

    processing_msg = await update.message.reply_text(
        f"⏳ A executar *{skill_name}*…", parse_mode="Markdown"
    )
    try:
        llm_client = context.application.bot_data.get("llm_client")
        ctx_manager = context.application.bot_data.get("context_manager")

        async def send_fn(msg: str) -> None:
            for chunk in _split(msg):
                await _send_md(update, chunk)

        await skill_runner.run_skill(
            skill, " ".join(args[1:]) or skill_name, ctx_manager, llm_client, send_fn
        )
        await processing_msg.delete()
    except Exception as exc:
        logger.exception("Error running skill %s: %s", skill_name, exc)
        await processing_msg.edit_text(
            f"❌ Erro ao executar *{skill_name}*: {exc}", parse_mode="Markdown"
        )


# ---------------------------------------------------------------------------
# /cron [list|pause|resume|delete|run|add]
# ---------------------------------------------------------------------------

async def cmd_cron(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    args = context.args or []
    scheduler = context.application.bot_data.get("scheduler")

    if not args:
        await update.message.reply_text(
            "*Comandos de cron:*\n\n"
            "/cron list — listar jobs\n"
            "/cron pause `<nome>` — pausar\n"
            "/cron resume `<nome>` — retomar\n"
            "/cron delete `<nome>` — eliminar\n"
            "/cron run `<nome>` — executar agora\n"
            "/cron add `<skill> <expr>` — adicionar",
            parse_mode="Markdown",
        )
        return

    subcmd, *rest = args

    if subcmd == "list":
        jobs = scheduler.list_jobs() if scheduler else []
        if not jobs:
            await update.message.reply_text("Nenhum cron job configurado.")
            return
        lines = ["*Cron Jobs:*\n"]
        for j in jobs:
            icon = "✅" if j.get("enabled") else "⏸"
            lines.append(
                f"{icon} *{j['skill_name']}* — `{j['cron_expr']}`\n"
                f"   Próx.: {j.get('next_run', 'n/d')}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif subcmd == "pause" and rest:
        if scheduler:
            await scheduler.pause_job(rest[0])
        await update.message.reply_text(f"⏸ Job *{rest[0]}* pausado.", parse_mode="Markdown")

    elif subcmd == "resume" and rest:
        if scheduler:
            await scheduler.resume_job(rest[0])
        await update.message.reply_text(f"▶️ Job *{rest[0]}* retomado.", parse_mode="Markdown")

    elif subcmd == "delete" and rest:
        if scheduler:
            await scheduler.delete_job(rest[0])
        await update.message.reply_text(f"🗑 Job *{rest[0]}* eliminado.", parse_mode="Markdown")

    elif subcmd == "run" and rest:
        if scheduler:
            await scheduler.run_now(rest[0])
        await update.message.reply_text(f"▶️ Job *{rest[0]}* executado.", parse_mode="Markdown")

    elif subcmd == "add" and len(rest) >= 2:
        skill_name, cron_expr = rest[0], " ".join(rest[1:])
        if scheduler:
            await scheduler.add_job(skill_name, cron_expr)
        await update.message.reply_text(
            f"✅ Job criado: *{skill_name}* — `{cron_expr}`",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("Argumento inválido. Usa /cron para ver os comandos.")


# ---------------------------------------------------------------------------
# /memory [clear]
# ---------------------------------------------------------------------------

async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    args = context.args or []
    ctx_manager = context.application.bot_data.get("context_manager")

    if not ctx_manager:
        await update.message.reply_text("Gestor de contexto não disponível.")
        return

    if args and args[0] == "clear":
        await ctx_manager.clear()
        await update.message.reply_text("🧹 Histórico de conversa limpo.")
    else:
        summary = await ctx_manager.get_summary()
        await update.message.reply_text(f"🧠 *Memória:*\n{summary}", parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /watch list
# ---------------------------------------------------------------------------

async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    args = context.args or []
    watchdog = context.application.bot_data.get("watchdog")

    if not args or args[0] != "list":
        await update.message.reply_text("Uso: /watch list")
        return

    watches = watchdog.list_watches() if watchdog else []
    if not watches:
        await update.message.reply_text("Nenhum ficheiro/pasta monitorizado.")
        return

    lines = ["*Monitorização ativa:*\n"]
    for w in watches:
        icon = "✅" if w.get("enabled") else "⏸"
        pattern = f" ({w['pattern']})" if w.get("pattern") else ""
        lines.append(f"{icon} `{w['path']}`{pattern}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /logs
# ---------------------------------------------------------------------------

async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    from config import get_config

    log_file = get_config().log_path / "assistant.log"
    if not log_file.exists():
        await update.message.reply_text("Sem logs disponíveis.")
        return

    with open(log_file, "r", encoding="utf-8") as fh:
        lines = fh.readlines()

    last_lines = "".join(lines[-10:]).strip()
    if not last_lines:
        await update.message.reply_text("Log vazio.")
        return

    await update.message.reply_text(
        f"```\n{last_lines[:3900]}\n```", parse_mode="Markdown"
    )


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return

    await update.message.reply_text(
        "*Comandos disponíveis:*\n\n"
        "🔧 *Controlo*\n"
        "/start — inicializar / onboarding\n"
        "/status — estado do sistema (LLM, skills, jobs)\n"
        "/help — esta ajuda\n\n"
        "🧩 *Skills*\n"
        "/skills — listar skills disponíveis\n"
        "/skill `<nome>` — executar skill\n"
        "/skill new — criar nova skill com o LLM\n\n"
        "⏰ *Cron*\n"
        "/cron list — listar jobs\n"
        "/cron pause|resume|delete|run|add …\n\n"
        "🧠 *Memória*\n"
        "/memory — ver resumo do histórico\n"
        "/memory clear — limpar histórico\n\n"
        "📁 *Ficheiros*\n"
        "/watch list — listar monitorizações ativas\n\n"
        "📋 *Outros*\n"
        "/logs — últimas 10 linhas de log\n\n"
        "_Também podes falar comigo em linguagem natural, sem comandos._",
        parse_mode="Markdown",
    )
