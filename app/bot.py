from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from app.config import Config


def create_bot(config: Config) -> Bot:
    return Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
