from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from app.db.database import Database
from app.db import queries
from app.db.models import WorkoutLogCreate
from app.utils.keyboards import log_status_kb, main_menu_kb


router = Router()


class LogStates(StatesGroup):
    waiting_status = State()


STATUS_MAP = {
    "выполнено": "done",
    "выполнил": "done",
    "сделал": "done",
    "готово": "done",
    "done": "done",
    "пропущено": "missed",
    "пропуск": "missed",
    "пропустил": "missed",
    "missed": "missed",
}


@router.callback_query(lambda c: c.data and c.data.startswith("workout:"))
async def workout_callback(query: CallbackQuery, db: Database) -> None:
    if query.data is None or query.from_user is None:
        logger.warning("⚠️ Получен callback workout без данных")
        return
    
    tg_id = query.from_user.id
    parts = query.data.split(":", 2)
    if len(parts) != 3:
        logger.warning(f"⚠️ Неверный формат callback workout: {query.data}")
        await query.answer("❌ Неверный формат", show_alert=True)
        return
    
    _, status_raw, workout_at_raw = parts
    status = status_raw.strip().lower()
    if status not in {"done", "missed"}:
        logger.warning(f"⚠️ Неверный статус в callback workout: {status}")
        await query.answer("❌ Неверный статус", show_alert=True)
        return

    user = await queries.get_user_by_tg_id(db, tg_id)
    if not user:
        logger.warning(f"⚠️ Попытка подтверждения тренировки несуществующим пользователем: tg_id={tg_id}")
        await query.answer("👋 Для начала работы выполните /start", show_alert=True)
        return

    try:
        workout_at = datetime.fromisoformat(workout_at_raw)
        user_id = int(user["id"])
        logger.info(f"🏋️ Подтверждение тренировки: user_id={user_id}, tg_id={tg_id}, status={status}, date={workout_at.strftime('%Y-%m-%d %H:%M')}")
        
        log = WorkoutLogCreate(user_id=user_id, date=workout_at, status=status)
        await queries.upsert_workout_log(db, log)
        logger.info(f"✅ Тренировка сохранена в БД: user_id={user_id}, status={status}")

        if status == "done":
            await query.answer("✅ Тренировка зачтена")
            if query.message:
                await query.message.answer(
                    "✅ <b>Тренировка зачтена!</b>\n\n"
                    "💪 Отличная работа! Продолжайте в том же ритме!"
                )
        else:
            await query.answer("⚠️ Пропуск зафиксирован")
            if query.message:
                await query.message.answer(
                    "⚠️ <b>Пропуск зафиксирован</b>\n\n"
                    "💪 Не расстраивайтесь! Следующая тренировка без срывов!"
                )
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке подтверждения тренировки: {e}", exc_info=True)
        await query.answer("❌ Произошла ошибка", show_alert=True)


@router.message(Command("log"))
async def log_command(message: Message, state: FSMContext, db: Database, tz: ZoneInfo) -> None:
    if message.text is None or message.from_user is None:
        return
    user = await queries.get_user_by_tg_id(db, message.from_user.id)
    if not user:
        await message.answer(
            "👋 Привет!\n\n"
            "Для начала работы выполните команду /start"
        )
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await state.set_state(LogStates.waiting_status)
        await message.answer(
            "Выберите статус тренировки:",
            reply_markup=log_status_kb().as_markup(),
        )
        return

    payload = parts[1].strip()
    tokens = payload.split()
    if not tokens:
        await message.answer(
            "❌ <b>Неверный формат</b>\n\n"
            "Пожалуйста, укажите статус:\n"
            "• <b>выполнено</b>\n"
            "• <b>пропущено</b>"
        )
        return

    status_token = tokens[0].lower()
    status = STATUS_MAP.get(status_token)
    if status is None:
        await message.answer(
            "❌ <b>Неверный статус</b>\n\n"
            "Пожалуйста, укажите:\n"
            "• <b>выполнено</b>\n"
            "• <b>пропущено</b>"
        )
        return

    duration = None
    notes = None
    if len(tokens) >= 2 and tokens[1].isdigit():
        duration = int(tokens[1])
        notes = " ".join(tokens[2:]) if len(tokens) > 2 else None
    else:
        notes = " ".join(tokens[1:]) if len(tokens) > 1 else None

    workout_at = datetime.now(tz).replace(second=0, microsecond=0)
    log = WorkoutLogCreate(
        user_id=int(user["id"]),
        date=workout_at,
        status=status,
        duration=duration,
        notes=notes,
    )
    await queries.upsert_workout_log(db, log)

    if status == "done":
        await message.answer(
            "✅ <b>Тренировка засчитана!</b>\n\n"
            "💪 Отличная работа! Продолжайте в том же духе!",
            reply_markup=main_menu_kb().as_markup()
        )
    else:
        await message.answer(
            "⚠️ <b>Пропуск зафиксирован</b>\n\n"
            "💪 Не расстраивайтесь! Следующая тренировка без срывов!",
            reply_markup=main_menu_kb().as_markup()
        )


@router.callback_query(LogStates.waiting_status, F.data.startswith("logstatus:"))
async def log_status_input(query, state: FSMContext, db: Database, tz: ZoneInfo) -> None:
    if query.data is None or query.from_user is None or query.message is None:
        return
    user = await queries.get_user_by_tg_id(db, query.from_user.id)
    if not user:
        await query.message.answer("Сначала выполните /start.")
        await state.clear()
        return

    status = query.data.split(":")[1]
    if status not in {"done", "missed"}:
        await query.answer("❌ Неверный статус", show_alert=True)
        return

    workout_at = datetime.now(tz).replace(second=0, microsecond=0)
    log = WorkoutLogCreate(
        user_id=int(user["id"]),
        date=workout_at,
        status=status,
    )
    await queries.upsert_workout_log(db, log)
    await state.clear()
    if status == "done":
        await query.message.answer(
            "✅ <b>Тренировка засчитана!</b>\n\n"
            "💪 Отличная работа! Продолжайте в том же духе!",
            reply_markup=main_menu_kb().as_markup()
        )
    else:
        await query.message.answer(
            "⚠️ <b>Пропуск зафиксирован</b>\n\n"
            "💪 Не расстраивайтесь! Следующая тренировка без срывов!",
            reply_markup=main_menu_kb().as_markup()
        )
    await query.answer()
