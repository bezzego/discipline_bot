from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import os


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: Path
    timezone: str
    log_level: str
    admin_ids: list[int]


def load_config() -> Config:
    load_dotenv(BASE_DIR / ".env")
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise RuntimeError("BOT_TOKEN is not set in .env")
    db_path = Path(os.getenv("DB_PATH", BASE_DIR / "data" / "discipline_bot.sqlite3"))
    timezone = os.getenv("TIMEZONE", "Europe/Moscow")
    log_level = os.getenv("LOG_LEVEL", "INFO")
    
    # Парсим список админов
    admin_ids_str = os.getenv("ADMIN_IDS", "").strip()
    admin_ids = []
    if admin_ids_str:
        try:
            admin_ids = [int(uid.strip()) for uid in admin_ids_str.split(",") if uid.strip()]
        except ValueError:
            admin_ids = []
    
    return Config(
        bot_token=bot_token,
        db_path=db_path,
        timezone=timezone,
        log_level=log_level,
        admin_ids=admin_ids,
    )
