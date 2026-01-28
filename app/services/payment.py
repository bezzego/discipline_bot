"""
Интеграция с ЮMoney через SDK (Quickpay + фоновая проверка статуса).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, date
import asyncio
from zoneinfo import ZoneInfo

from yoomoney import Client, Quickpay

from app.config import Config
from app.db.database import Database
from app.db import queries

logger = logging.getLogger(__name__)

# Для отправки уведомлений пользователю
_bot_instance = None

def set_bot_instance(bot) -> None:
    """Установить экземпляр бота для отправки уведомлений."""
    global _bot_instance
    _bot_instance = bot


def get_bot_instance():
    """Получить экземпляр бота для отправки уведомлений."""
    return _bot_instance


def _get_client(config: Config) -> Client:
    if not config.yoomoney_api_token:
        raise RuntimeError("YOOMONEY_API_TOKEN не задан")
    return Client(config.yoomoney_api_token.strip())


def _amounts_close(a: float, b: float, eps: float = 0.01) -> bool:
    return abs(a - b) <= eps


async def create_payment_link(
    db: Database,
    user_id: int,
    tg_id: int,
    amount: float,
    description: str,
    return_url: str,
    tz: ZoneInfo,
    config: Config,
    is_recurring: bool = False,
) -> tuple[str, str]:
    """
    Создать платеж через ЮMoney Quickpay и вернуть ссылку на оплату.
    Возвращает (payment_id, payment_url).
    """
    if not config.yoomoney_wallet_id or not config.yoomoney_api_token:
        raise RuntimeError("ЮMoney не настроен (YOOMONEY_WALLET_ID или YOOMONEY_API_TOKEN не заданы)")

    wallet_id = config.yoomoney_wallet_id.strip()

    # Генерируем уникальный label для отслеживания платежа
    payment_label = uuid.uuid4().hex

    quickpay = Quickpay(
        receiver=wallet_id,
        quickpay_form="shop",
        targets=description[:150],
        paymentType="SB",
        sum=f"{amount:.2f}",
        label=payment_label[:64],
        successURL=return_url,
    )
    payment_url = quickpay.redirected_url

    # Сохраняем платеж в БД со статусом pending
    await queries.create_payment(
        db=db,
        user_id=user_id,
        payment_id=payment_label,  # Используем label как payment_id
        amount=amount,
        currency="RUB",
        status="pending",
        payment_method_id=None,
        created_at=datetime.now(tz),
    )

    logger.info(
        f"💰 Quickpay платеж создан: label={payment_label}, user_id={user_id}, "
        f"amount={amount}"
    )

    return payment_label, payment_url


async def _process_success_payment(
    db: Database,
    payment_label: str,
    tz: ZoneInfo,
    paid_at: datetime | None = None,
    operation_id: str | None = None,
) -> None:
    payment_db = await queries.get_payment_by_id(db, payment_label)
    if not payment_db:
        logger.warning(f"⚠️ Платеж не найден в БД: label={payment_label}")
        return

    if payment_db.get("status") == "succeeded":
        logger.info(f"ℹ️ Платеж уже подтвержден: label={payment_label}")
        return

    user_id = int(payment_db["user_id"])

    await queries.update_payment_status(
        db=db,
        payment_id=payment_label,
        status="succeeded",
        paid_at=paid_at or datetime.now(tz),
    )

    now = datetime.now(tz)
    user = await queries.get_user_by_id(db, user_id)
    base_date = now.date()
    if user:
        sub_ends = user.get("subscription_ends_at")
        if sub_ends:
            try:
                sub_end_date = date.fromisoformat(str(sub_ends)[:10])
                if sub_end_date >= base_date:
                    base_date = sub_end_date
            except Exception:
                pass

    end_date = (base_date + timedelta(days=30)).isoformat()
    await queries.set_subscription_ends_at(db, user_id, end_date)

    logger.info(
        f"✅ Платеж успешен: label={payment_label}, user_id={user_id}, "
        f"subscription_ends_at={end_date}, operation_id={operation_id or 'unknown'}"
    )

    if user and _bot_instance:
        try:
            tg_id = int(user["tg_id"])
            await _bot_instance.send_message(
                tg_id,
                "✅ <b>Оплата прошла успешно!</b>\n\n"
                f"Доступ открыт на <b>30 дней</b> (до {end_date}).\n"
                "Можете пользоваться ботом без ограничений.",
            )
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке уведомления пользователю {user_id}: {e}")


async def _check_payment_status(
    label: str,
    config: Config,
) -> tuple[str | None, datetime | None, str | None, float | None]:
    def _fetch() -> tuple[str | None, datetime | None, str | None, float | None]:
        client = _get_client(config)
        history = client.operation_history(label=label)
        for operation in history.operations:
            if getattr(operation, "label", None) != label:
                continue
            status = getattr(operation, "status", None)
            if status == "success":
                paid_at = getattr(operation, "datetime", None)
                operation_id = getattr(operation, "operation_id", None)
                amount = getattr(operation, "amount", None)
                return "success", paid_at, operation_id, amount
            if status in {"refused", "rejected", "canceled"}:
                return status, None, getattr(operation, "operation_id", None), None
        return None, None, None, None

    return await asyncio.to_thread(_fetch)


async def check_pending_payments(
    db: Database,
    tz: ZoneInfo,
    config: Config,
) -> None:
    """
    Проверить статусы pending платежей.
    Для SDK используем запрос operation_history по label.
    """
    pending_payments = await queries.get_pending_payments(db)
    
    if pending_payments:
        logger.info(f"⏰ Найдено {len(pending_payments)} pending платежей")

        for payment in pending_payments:
            label = payment.get("payment_id")
            if not label:
                continue
            try:
                status, paid_at, operation_id, amount = await _check_payment_status(label, config)
            except Exception as e:
                logger.error(f"❌ Ошибка проверки платежа {label}: {e}")
                continue

            if status == "success":
                if amount is not None:
                    try:
                        expected = float(payment.get("amount", 0))
                        if not _amounts_close(float(amount), expected):
                            logger.warning(
                                f"⚠️ Сумма не совпадает для {label}: ожидали {expected}, пришло {amount}"
                            )
                    except Exception:
                        pass
                await _process_success_payment(
                    db=db,
                    payment_label=label,
                    tz=tz,
                    paid_at=paid_at if isinstance(paid_at, datetime) else None,
                    operation_id=operation_id,
                )
            elif status in {"refused", "rejected", "canceled"}:
                await queries.update_payment_status(
                    db=db,
                    payment_id=label,
                    status="canceled",
                    paid_at=None,
                )
                logger.info(f"❌ Платеж отклонен: label={label}, status={status}")


async def create_recurring_payment(
    db: Database,
    user_id: int,
    tg_id: int,
    payment_method_id: str,
    amount: float,
    description: str,
    tz: ZoneInfo,
    config: Config,
) -> tuple[str, str]:
    """
    Создать рекуррентный платеж через Quickpay.
    Для Quickpay рекуррентные платежи не поддерживаются напрямую,
    поэтому создаем обычный платеж.
    """
    return await create_payment_link(
        db=db,
        user_id=user_id,
        tg_id=tg_id,
        amount=amount,
        description=description,
        return_url="https://t.me",
        tz=tz,
        config=config,
        is_recurring=False,
    )


async def process_recurring_payments(
    db: Database,
    bot,
    tz: ZoneInfo,
    config: Config,
) -> None:
    """
    Обработать рекуррентные платежи.
    Для Quickpay рекуррентные платежи не поддерживаются напрямую,
    поэтому отправляем пользователям напоминание об оплате.
    """
    today = datetime.now(tz).date().isoformat()
    subscriptions = await queries.get_recurring_subscriptions_due(db, today)

    logger.info(f"🔄 Проверка рекуррентных подписок: найдено {len(subscriptions)} подписок")

    for sub in subscriptions:
        user_id = int(sub["user_id"])
        amount = float(sub["amount"])

        user = await queries.get_user_by_id(db, user_id)
        if not user:
            logger.warning(f"⚠️ Пользователь не найден: user_id={user_id}")
            continue

        tg_id = int(user["tg_id"])

        try:
            # Для Quickpay отправляем напоминание об оплате
            await bot.send_message(
                tg_id,
                "⏰ <b>Время продлить подписку</b>\n\n"
                f"Подписка истекает. Пожалуйста, продлите доступ на <b>{amount:.0f} ₽</b>.\n\n"
                "Используйте кнопку 'Продлить подписку' в меню.",
            )
            logger.info(f"📧 Напоминание об оплате отправлено: user_id={user_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке напоминания пользователю {tg_id}: {e}")
