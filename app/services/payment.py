"""
Интеграция с ЮMoney для оплаты и рекуррентных платежей.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from yookassa import Configuration, Payment

from app.config import Config
from app.db.database import Database
from app.db import queries
from app.services.access import get_subscription_price_rub, subscription_end_after_months

logger = logging.getLogger(__name__)

# Для отправки уведомлений пользователю
_bot_instance = None


def set_bot_instance(bot) -> None:
    """Установить экземпляр бота для отправки уведомлений."""
    global _bot_instance
    _bot_instance = bot


def init_yoomoney(config: Config) -> None:
    """Инициализация ЮMoney."""
    Configuration.account_id = config.yoomoney_shop_id
    Configuration.secret_key = config.yoomoney_secret_key
    logger.info(f"✅ ЮMoney инициализирован: shop_id={config.yoomoney_shop_id}, test_mode={config.yoomoney_test_mode}")


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
    Создать платеж в ЮMoney и вернуть ссылку на оплату.
    Возвращает (payment_id, confirmation_url).
    """
    if not config.yoomoney_shop_id or not config.yoomoney_secret_key:
        raise RuntimeError("ЮMoney не настроен (YOOMONEY_SHOP_ID или YOOMONEY_SECRET_KEY не заданы)")

    init_yoomoney(config)

    payment_data = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "confirmation": {
            "type": "redirect",
            "return_url": return_url,
        },
        "capture": True,
        "description": description,
        "metadata": {
            "user_id": str(user_id),
            "tg_id": str(tg_id),
            "is_recurring": "1" if is_recurring else "0",
        },
    }

    if is_recurring:
        payment_data["payment_method_data"] = {
            "type": "bank_card",
        }
        payment_data["save_payment_method"] = True

    try:
        payment = Payment.create(payment_data, idempotency_key=f"{user_id}_{datetime.now(tz).isoformat()}")
        payment_id = payment.id
        confirmation_url = payment.confirmation.confirmation_url

        payment_method_id = None
        if payment.payment_method:
            payment_method_id = payment.payment_method.id

        await queries.create_payment(
            db=db,
            user_id=user_id,
            payment_id=payment_id,
            amount=amount,
            currency="RUB",
            status=payment.status,
            payment_method_id=payment_method_id,
            created_at=datetime.now(tz),
        )

        logger.info(
            f"💰 Платеж создан: payment_id={payment_id}, user_id={user_id}, "
            f"amount={amount}, is_recurring={is_recurring}"
        )

        return payment_id, confirmation_url
    except Exception as e:
        logger.error(f"❌ Ошибка при создании платежа: {e}", exc_info=True)
        raise


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
    Создать рекуррентный платеж (автоплатеж) в ЮMoney.
    Возвращает (payment_id, status).
    """
    if not config.yoomoney_shop_id or not config.yoomoney_secret_key:
        raise RuntimeError("ЮMoney не настроен")

    init_yoomoney(config)

    payment_data = {
        "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
        "capture": True,
        "description": description,
        "payment_method_id": payment_method_id,
        "metadata": {
            "user_id": str(user_id),
            "tg_id": str(tg_id),
            "is_recurring": "1",
        },
    }

    try:
        payment = Payment.create(payment_data, idempotency_key=f"{user_id}_recurring_{datetime.now(tz).isoformat()}")
        payment_id = payment.id

        await queries.create_payment(
            db=db,
            user_id=user_id,
            payment_id=payment_id,
            amount=amount,
            currency="RUB",
            status=payment.status,
            payment_method_id=payment_method_id,
            created_at=datetime.now(tz),
        )

        logger.info(
            f"🔄 Рекуррентный платеж создан: payment_id={payment_id}, user_id={user_id}, "
            f"amount={amount}, payment_method_id={payment_method_id}"
        )

        return payment_id, payment.status
    except Exception as e:
        logger.error(f"❌ Ошибка при создании рекуррентного платежа: {e}", exc_info=True)
        raise


async def _process_successful_payment(
    db: Database,
    payment_id: str,
    payment_db: dict,
    payment_object,
    tz: ZoneInfo,
) -> None:
    """Обработать успешный платеж: обновить подписку, создать рекуррентную подписку, отправить уведомление."""
    user_id = int(payment_db["user_id"])
    amount = float(payment_object.amount.value)
    payment_method_id = payment_object.payment_method.id if payment_object.payment_method else None

    now = datetime.now(tz)
    end_date = subscription_end_after_months(now)
    await queries.set_subscription_ends_at(db, user_id, end_date)

    # Обновляем payment_method_id в платеже, если он был сохранен
    if payment_method_id and not payment_db.get("payment_method_id"):
        await db.execute(
            "UPDATE payments SET payment_method_id = ? WHERE payment_id = ?;",
            (payment_method_id, payment_id),
        )

    # Если это первый платеж с сохранением метода, создаем рекуррентную подписку
    existing_recurring = await queries.get_recurring_subscription(db, user_id)
    if payment_method_id and not existing_recurring:
        next_payment = (now + timedelta(days=30)).date().isoformat()
        await queries.create_recurring_subscription(
            db=db,
            user_id=user_id,
            payment_method_id=payment_method_id,
            amount=amount,
            currency="RUB",
            next_payment_date=next_payment,
            created_at=now,
        )
        logger.info(
            f"🔄 Рекуррентная подписка создана: user_id={user_id}, "
            f"payment_method_id={payment_method_id}, next_payment={next_payment}"
        )

    logger.info(
        f"✅ Платеж успешен: payment_id={payment_id}, user_id={user_id}, "
        f"subscription_ends_at={end_date}"
    )

    # Отправляем уведомление пользователю
    user = await queries.get_user_by_id(db, user_id)
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


async def check_pending_payments(
    db: Database,
    tz: ZoneInfo,
    config: Config,
) -> None:
    """
    Проверить статусы pending платежей через API ЮMoney.
    Вызывается периодически (каждую минуту).
    """
    if not config.yoomoney_shop_id or not config.yoomoney_secret_key:
        return

    init_yoomoney(config)

    pending_payments = await queries.get_pending_payments(db)
    if not pending_payments:
        return

    logger.debug(f"🔍 Проверка {len(pending_payments)} pending платежей")

    for payment_db in pending_payments:
        payment_id = payment_db["payment_id"]
        old_status = payment_db["status"]

        try:
            # Получаем актуальный статус платежа из API
            payment_object = Payment.find_one(payment_id)
            new_status = payment_object.status

            # Если статус не изменился, пропускаем
            if new_status == old_status:
                continue

            logger.info(
                f"📊 Статус платежа изменился: payment_id={payment_id}, "
                f"{old_status} → {new_status}"
            )

            # Обновляем статус в БД
            paid_at = None
            if payment_object.captured_at:
                try:
                    paid_at = datetime.fromisoformat(payment_object.captured_at.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pass

            await queries.update_payment_status(
                db=db,
                payment_id=payment_id,
                status=new_status,
                paid_at=paid_at,
            )

            # Обрабатываем успешный платеж
            if new_status == "succeeded":
                await _process_successful_payment(
                    db=db,
                    payment_id=payment_id,
                    payment_db=payment_db,
                    payment_object=payment_object,
                    tz=tz,
                )
            elif new_status == "canceled":
                user_id = int(payment_db["user_id"])
                logger.info(f"❌ Платеж отменен: payment_id={payment_id}, user_id={user_id}")

        except Exception as e:
            logger.error(
                f"❌ Ошибка при проверке платежа {payment_id}: {e}",
                exc_info=True,
            )


async def process_recurring_payments(
    db: Database,
    bot,
    tz: ZoneInfo,
    config: Config,
) -> None:
    """
    Обработать рекуррентные платежи, у которых наступила дата следующего платежа.
    Вызывается периодически (например, раз в день).
    """
    today = datetime.now(tz).date().isoformat()
    subscriptions = await queries.get_recurring_subscriptions_due(db, today)

    logger.info(f"🔄 Проверка рекуррентных платежей: найдено {len(subscriptions)} подписок")

    for sub in subscriptions:
        user_id = int(sub["user_id"])
        payment_method_id = sub["payment_method_id"]
        amount = float(sub["amount"])

        user = await queries.get_user_by_id(db, user_id)
        if not user:
            logger.warning(f"⚠️ Пользователь не найден для рекуррентной подписки: user_id={user_id}")
            continue

        tg_id = int(user["tg_id"])

        try:
            payment_id, status = await create_recurring_payment(
                db=db,
                user_id=user_id,
                tg_id=tg_id,
                payment_method_id=payment_method_id,
                amount=amount,
                description=f"Автоплатеж подписки Discipline Bot (месяц)",
                tz=tz,
                config=config,
            )

            if status == "succeeded":
                next_payment = (datetime.now(tz) + timedelta(days=30)).date().isoformat()
                await queries.update_recurring_subscription_next_payment(
                    db=db,
                    user_id=user_id,
                    next_payment_date=next_payment,
                )
                logger.info(
                    f"✅ Рекуррентный платеж успешен: payment_id={payment_id}, user_id={user_id}, "
                    f"next_payment={next_payment}"
                )

                try:
                    await bot.send_message(
                        tg_id,
                        "✅ <b>Автоплатеж выполнен</b>\n\n"
                        f"Подписка продлена на <b>30 дней</b>.\n"
                        f"Следующий платеж: <b>{next_payment}</b>",
                    )
                except Exception as e:
                    logger.error(f"❌ Ошибка при отправке уведомления пользователю {tg_id}: {e}")

            elif status == "canceled":
                await queries.deactivate_recurring_subscription(db, user_id)
                logger.warning(f"⚠️ Рекуррентный платеж отменен, подписка деактивирована: user_id={user_id}")

                try:
                    await bot.send_message(
                        tg_id,
                        "⚠️ <b>Автоплатеж не выполнен</b>\n\n"
                        "Платеж был отклонен. Пожалуйста, оформите подписку заново.",
                    )
                except Exception as e:
                    logger.error(f"❌ Ошибка при отправке уведомления пользователю {tg_id}: {e}")

        except Exception as e:
            logger.error(
                f"❌ Ошибка при обработке рекуррентного платежа для user_id={user_id}: {e}",
                exc_info=True,
            )
