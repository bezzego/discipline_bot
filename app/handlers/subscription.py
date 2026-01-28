"""Оплата подписки через ЮMoney."""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import Config
from app.db.database import Database
from app.db import queries
from app.services.access import (
    PRODUCT_DESCRIPTION,
    get_product_price_text,
    get_subscription_price_rub,
    TRIAL_DAYS,
    access_status_display,
)
from app.services.payment import create_payment_link
from app.utils.keyboards import paywall_kb, subscription_kb

logger = logging.getLogger(__name__)

router = Router()

async def get_tariff_base_text(db: Database) -> str:
    """Получить базовый текст тарифа с актуальной ценой."""
    product_price = await get_product_price_text(db)
    return (
        "📋 <b>Описание и стоимость товаров/услуг</b>\n\n"
        f"{PRODUCT_DESCRIPTION}\n\n"
        f"{product_price}\n\n"
        f"🆓 Бесплатный период: <b>{TRIAL_DAYS} дней</b>. Затем — подписка по указанной стоимости."
    )


@router.message(Command("tariff"))
async def tariff_command(
    message: Message,
    db: Database,
    tz: ZoneInfo,
    config: Config,
) -> None:
    """Показать описание и стоимость; персональный статус + «Оплатить сейчас» при триале."""
    tariff_base = await get_tariff_base_text(db)
    if message.from_user is None:
        await message.answer(tariff_base)
        return
    user = await queries.get_user_by_tg_id(db, message.from_user.id)
    if not user:
        await message.answer(tariff_base)
        return
    status_text, pay_now, extend = access_status_display(
        user, message.from_user.id, config, tz
    )
    text = f"🔐 <b>Ваш статус:</b> {status_text}\n\n{tariff_base}"
    kb = subscription_kb(pay_now=pay_now, extend=extend, price=await get_subscription_price_rub(db))
    if pay_now or extend:
        await message.answer(text, reply_markup=kb.as_markup())
    else:
        await message.answer(text)


@router.callback_query(F.data.startswith("pay:"))
async def pay_handler(
    query: CallbackQuery,
    db: Database,
    tz: ZoneInfo,
    config: Config,
) -> None:
    """Создать платеж через ЮMoney."""
    if query.data is None or query.message is None or query.from_user is None:
        return
    if not query.data.startswith("pay:month"):
        await query.answer()
        return

    user = await queries.get_user_by_tg_id(db, query.from_user.id)
    if not user:
        await query.answer("Сначала выполните /start", show_alert=True)
        return

    # Проверяем, есть ли настройки ЮMoney
    if not config.yoomoney_wallet_id or not config.yoomoney_api_token:
        await query.answer("⚠️ Платежная система не настроена", show_alert=True)
        logger.error("❌ ЮMoney не настроен: отсутствуют YOOMONEY_WALLET_ID или YOOMONEY_API_TOKEN")
        return

    try:
        # Получаем актуальную цену из БД
        price = await get_subscription_price_rub(db)
        
        # Получаем username бота для return_url
        bot_info = await query.message.bot.get_me()
        bot_username = bot_info.username if bot_info.username else None
        return_url = f"https://t.me/{bot_username}" if bot_username else "https://t.me"
        
        # Создаем платеж с возможностью рекуррентных платежей
        is_recurring = True  # Включаем рекуррентные платежи по умолчанию
        
        payment_id, payment_url = await create_payment_link(
            db=db,
            user_id=int(user["id"]),
            tg_id=query.from_user.id,
            amount=price,
            description="Подписка Discipline Bot (1 месяц)",
            return_url=return_url,
            tz=tz,
            config=config,
            is_recurring=is_recurring,
        )

        await query.message.edit_text(
            "💳 <b>Оплата подписки</b>\n\n"
            f"Сумма: <b>{price:.0f} ₽</b>\n\n"
            "Нажмите на кнопку ниже для перехода к оплате.\n\n"
            "После успешной оплаты доступ откроется автоматически.\n\n"
            f"ID платежа: <code>{payment_id}</code>",
            reply_markup=None,
        )

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        
        kb = InlineKeyboardBuilder()
        # Открываем оплату во внешнем браузере, чтобы страница ЮMoney работала корректно
        kb.button(text="💳 Оплатить", url=payment_url)
        kb.button(text="◀️ Отмена", callback_data="menu:back")
        kb.adjust(1, 1)

        await query.message.answer(
            "Нажмите кнопку ниже для оплаты. После оплаты доступ откроется автоматически.",
            reply_markup=kb.as_markup(),
        )
        await query.answer()

        logger.info(
            f"💰 Платеж создан: payment_id={payment_id}, user_id={user['id']}, "
            f"tg_id={query.from_user.id}, amount={price}"
        )

    except Exception as e:
        logger.error(f"❌ Ошибка при создании платежа: {e}", exc_info=True)
        await query.answer("❌ Ошибка при создании платежа. Попробуйте позже.", show_alert=True)
