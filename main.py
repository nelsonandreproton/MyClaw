import asyncio
import logging
import signal
import time

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import get_config
from memory.store import MemoryStore
from memory.migrations import run_migrations
from memory.crypto import CryptoManager
from llm.client import LLMClient
from llm.context import ContextManager
from scheduler.manager import SchedulerManager
from watchdog_manager import WatchdogManager
from skills.runner import SkillRunner
from bot.handlers import message_handler
from bot.commands import (
    cmd_start,
    cmd_status,
    cmd_skills,
    cmd_skill,
    cmd_cron,
    cmd_memory,
    cmd_watch,
    cmd_logs,
    cmd_help,
    handle_onboarding_callback,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    config = get_config()  # validates env + sets up logging
    logger.info("Starting %s", config.assistant_name)

    # 1. Database
    store = MemoryStore(config.db_path)
    await store.init()
    await run_migrations(store)
    logger.info("Database ready at %s", config.db_path)

    # 2. Core services
    crypto = CryptoManager(config.secret_key)
    llm_client = LLMClient(config)
    ctx_manager = ContextManager(store)

    # 3. Scheduler
    scheduler = SchedulerManager(store)
    await scheduler.start()

    # 4. Watchdog
    watchdog = WatchdogManager(store)
    await watchdog.start()

    # 5. Skills
    skill_runner = SkillRunner(
        config.skills_path,
        store=store,
        crypto=crypto,
        max_retries=config.max_retries,
        timeout=config.execution_timeout,
    )
    await skill_runner.load()
    logger.info("Loaded %d skills", len(skill_runner.skills))

    # 6. Telegram bot
    app = Application.builder().token(config.telegram_bot_token).build()

    app.bot_data.update(
        {
            "config": config,
            "store": store,
            "crypto": crypto,
            "llm_client": llm_client,
            "context_manager": ctx_manager,
            "skill_runner": skill_runner,
            "scheduler": scheduler,
            "watchdog": watchdog,
            "start_time": time.monotonic(),
        }
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("skills", cmd_skills))
    app.add_handler(CommandHandler("skill", cmd_skill))
    app.add_handler(CommandHandler("cron", cmd_cron))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(
        CallbackQueryHandler(handle_onboarding_callback, pattern="^skill_")
    )
    # Text messages — must be registered last
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    # Graceful shutdown via OS signals (Unix only; Ctrl+C works on all platforms)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
    except NotImplementedError:
        pass  # Windows — KeyboardInterrupt will trigger CancelledError instead

    logger.info("%s is ready, starting Telegram polling…", config.assistant_name)

    try:
        async with app:
            await app.start()
            await app.updater.start_polling(
                allowed_updates=["message", "callback_query"]
            )
            try:
                await stop_event.wait()
            except asyncio.CancelledError:
                pass
            logger.info("Stopping…")
            await app.updater.stop()
            await app.stop()
    finally:
        await watchdog.stop()
        await scheduler.stop()
        await store.close()
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
