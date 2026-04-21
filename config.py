import logging
import logging.handlers
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_allowed_user_id: int
    lm_studio_base_url: str
    lm_studio_model: str
    lm_studio_timeout: int
    assistant_name: str
    secret_key: str
    db_path: Path
    skills_path: Path
    log_path: Path
    log_level: str
    max_retries: int
    execution_timeout: int


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def _load_config() -> Config:
    _validate_required_env(["TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_ID", "SECRET_KEY"])

    db_path = Path(os.getenv("DB_PATH", "./data/assistant.db"))
    skills_path = Path(os.getenv("SKILLS_PATH", "./skills"))
    log_path = Path(os.getenv("LOG_PATH", "./logs"))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.mkdir(parents=True, exist_ok=True)

    config = Config(
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        telegram_allowed_user_id=int(os.environ["TELEGRAM_ALLOWED_USER_ID"]),
        lm_studio_base_url=os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1"),
        lm_studio_model=os.getenv("LM_STUDIO_MODEL", "qwen2.5-coder-14b-instruct"),
        lm_studio_timeout=int(os.getenv("LM_STUDIO_TIMEOUT", "120")),
        assistant_name=os.getenv("ASSISTANT_NAME", "Claw"),
        secret_key=os.environ["SECRET_KEY"],
        db_path=db_path,
        skills_path=skills_path,
        log_path=log_path,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        execution_timeout=int(os.getenv("EXECUTION_TIMEOUT", "30")),
    )

    _setup_logging(config)
    return config


def _validate_required_env(keys: list[str]) -> None:
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


def _setup_logging(config: Config) -> None:
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        config.log_path / "assistant.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(log_level)
        root.addHandler(file_handler)
        root.addHandler(console_handler)
