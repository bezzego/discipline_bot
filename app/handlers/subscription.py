"""Оплата подписки (пока симуляция)."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.db.database import Database
from app.db import queries
from app.services.access import (
    PRODUCT_DESCRIPTION,
    PRODUCT_PRICE,
    TRIAL_DAYS,
    subscription_end_after_months,
)
from app.utils.keyboards import main_menu_kb, paywall_kb

logger = logging.getLogger(__name__)

router = Router()

TARIFF_TEXT = (
    "📋 <b>Описание и стоимость товаров/услуг</b>\n\n"
    f"{PRODUCT_DESCRIPTION}\n\n"
    f"{PRODUCT_PRICE}\n\n"
    f"🆓 Бесплатный период: <b>{TRIAL_DAYS} дней</b>. Затем — подписка по указанной стоимости."
)


@router.message(Command("tariff"))
async def tariff_command(message: Message) -> None:
    """Показать описание и стоимость подписки (доступно всем)."""
    await message.answer(TARIFF_TEXT)


@router.callback_query(F.data.startswith("pay:"))
async def pay_handler(
    query: CallbackQuery,
    db: Database,
    tz: ZoneInfo,
    config: Config,
) -> None:
    if query.data is None or query.message is None or query.from_user is None:
        return
    if not query.data.startswith("pay:month"):
        await query.answer()
        return

    user = await queries.get_user_by_tg_id(db, query.from_user.id)
    if not user:
        await query.answer("Сначала выполните /start", show_alert=True)
        return

    now = datetime.now(tz)
    end = subscription_end_after_months(now)
    await queries.set_subscription_ends_at(db, int(user["id"]), end)
    logger.info(f"💰 Подписка оформлена (симуляция): user_id={user['id']}, tg_id={query.from_user.id}, до {end}")

    await query.message.edit_text(
        "✅ <b>Оплата прошла успешно!</b>\n\n"
        "Доступ открыт на <b>30 дней</b>. Можете пользоваться ботом без ограничений.",
        reply_markup=None,
    )
    await query.message.answer(
        "Главное меню:",
        reply_markup=main_menu_kb(config.admin_ids, query.from_user.id).as_markup(),
    )
    await query.answer()
