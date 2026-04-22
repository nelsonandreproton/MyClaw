import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.middleware import is_authorized, is_rate_limited

logger = logging.getLogger(__name__)

_TELEGRAM_MAX = 4096  # Telegram message length limit


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_authorized(update):
        return
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    if is_rate_limited(user.id):
        await update.message.reply_text("Demasiadas mensagens. Aguarda um momento.")
        return

    text = update.message.text.strip()
    bot_data = context.application.bot_data
    ctx_manager = bot_data.get("context_manager")
    llm_client = bot_data.get("llm_client")
    skill_runner = bot_data.get("skill_runner")

    if ctx_manager:
        await ctx_manager.add_message("user", text)

    skill = skill_runner.match_skill(text) if skill_runner else None

    processing_msg = await update.message.reply_text("⏳ A processar…")

    try:
        if skill and skill_runner:
            async def send_fn(msg: str) -> None:
                for chunk in _split(msg):
                    await _send_md(update, chunk)

            await skill_runner.run_skill(skill, text, ctx_manager, llm_client, send_fn)
            await processing_msg.delete()

        else:
            from llm.prompts import build_system_prompt
            from config import get_config

            cfg = get_config()
            history = await ctx_manager.get_context() if ctx_manager else []
            skills_list = list(skill_runner.skills.keys()) if skill_runner else []
            system = build_system_prompt(cfg.assistant_name, skills_list)

            response = await llm_client.chat(history, system_prompt=system)

            if ctx_manager:
                await ctx_manager.add_message("assistant", response)

            await processing_msg.delete()
            for chunk in _split(response):
                await _send_md(update, chunk)

    except Exception as exc:
        logger.exception("Error in message_handler: %s", exc)
        try:
            await processing_msg.edit_text("❌ Erro inesperado. Consulta /logs para detalhes.")
        except Exception:
            pass


async def _send_md(update: Update, text: str) -> None:
    try:
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(text)


def _split(text: str, max_len: int = _TELEGRAM_MAX) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks
