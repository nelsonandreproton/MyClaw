import logging
import threading
import time
from collections import defaultdict

from telegram import Update

from config import get_config

logger = logging.getLogger(__name__)

_RATE_LIMIT = 10   # max messages per window
_RATE_WINDOW = 60  # seconds

# Per-user timestamps of recent messages (in-memory, resets on restart)
_message_times: dict[int, list[float]] = defaultdict(list)
_rate_lock = threading.Lock()


def is_authorized(update: Update) -> bool:
    config = get_config()
    user = update.effective_user
    if not user:
        return False
    if user.id != config.telegram_allowed_user_id:
        logger.warning(
            "Unauthorized access: user_id=%d username=%s",
            user.id,
            user.username or "unknown",
        )
        return False
    return True


def is_rate_limited(user_id: int) -> bool:
    with _rate_lock:
        now = time.monotonic()
        times = _message_times[user_id]
        times[:] = [t for t in times if now - t < _RATE_WINDOW]
        if len(times) >= _RATE_LIMIT:
            logger.warning("Rate limit hit for user_id=%d", user_id)
            return True
        times.append(now)
        return False
