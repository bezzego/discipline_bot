from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot

from app.db.database import Database
from app.db.models import WorkoutLogCreate
from app.db import queries
from app.utils.keyboards import workout_confirmation_kb

logger = logging.getLogger(__name__)


async def send_workout_reminder(bot: Bot, tg_id: int, workout_at: datetime) -> None:
    time_str = workout_at.strftime("%H:%M")
    await bot.send_message(
        tg_id,
        f"⏰ Напоминание: тренировка через 2 часа в {time_str}.\nПодготовьтесь и будьте вовремя!",
    )


async def ask_workout_confirmation(bot: Bot, tg_id: int, workout_at: datetime) -> None:
    time_str = workout_at.strftime("%H:%M")
    kb = workout_confirmation_kb(workout_at.isoformat()).as_markup()
    try:
        await bot.send_message(
            tg_id,
            f"🏋️ <b>Время тренировки: {time_str}</b>\n\n"
            "Подтвердите выполнение:",
            reply_markup=kb,
        )
        logger.info(f"✅ Запрос подтверждения тренировки отправлен: tg_id={tg_id}, время={time_str}")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке запроса подтверждения пользователю {tg_id}: {e}", exc_info=True)


async def mark_missed_if_no_response(
    db: Database,
    bot: Bot,
    user_id: int,
    tg_id: int,
    workout_at: datetime,
) -> None:
    if await queries.workout_log_exists(db, user_id, workout_at):
        logger.debug(f"ℹ️ Тренировка уже залогирована: user_id={user_id}, date={workout_at}")
        return
    
    logger.info(f"⚠️ Тренировка не подтверждена, отмечаем как пропуск: user_id={user_id}, date={workout_at}")
    log = WorkoutLogCreate(user_id=user_id, date=workout_at, status="missed")
    await queries.upsert_workout_log(db, log)
    
    try:
        await bot.send_message(
            tg_id,
            "⚠️ <b>Тренировка не подтверждена</b>\n\n"
            "Тренировка засчитана как пропуск.\n\n"
            "💪 <b>Дисциплина — это действие, а не намерение.</b>\n"
            "Вернитесь в ритм на следующей тренировке!"
        )
        logger.info(f"✅ Уведомление о пропуске отправлено: user_id={user_id}, tg_id={tg_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке уведомления о пропуске пользователю {tg_id}: {e}", exc_info=True)
