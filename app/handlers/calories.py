from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from app.config import Config
from app.db.database import Database
from app.db import queries
from app.utils.keyboards import main_menu_kb
from app.utils.parsing import parse_calories

logger = logging.getLogger(__name__)

router = Router()


class CalorieStates(StatesGroup):
    waiting_calories = State()


@router.message(Command("calories"))
async def calories_command(
    message: Message,
    state: FSMContext,
    db: Database,
    tz: ZoneInfo,
    config: Config,
) -> None:
    if message.from_user is None:
        return
    user = await queries.get_user_by_tg_id(db, message.from_user.id)
    if not user:
        await message.answer("👋 Для начала работы выполните /start")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1:
        try:
            cals = parse_calories(parts[1])
        except ValueError:
            await message.answer(
                "❌ <b>Неверный формат</b>\n\n"
                "Укажите калории целым числом, например: <code>500</code> или <code>1200</code>"
            )
            return
        await _add_and_confirm(message, db, tz, config, int(user["id"]), message.from_user.id, cals)
        return

    await state.set_state(CalorieStates.waiting_calories)
    await state.update_data(user_id=int(user["id"]))
    await message.answer(
        "🔥 <b>Добавить калории</b>\n\n"
        "Введите количество ккал (целое число).\n\n"
        "Примеры: <code>500</code>, <code>1200</code>"
    )


@router.message(CalorieStates.waiting_calories, F.text)
async def calories_input(
    message: Message,
    state: FSMContext,
    db: Database,
    tz: ZoneInfo,
    config: Config,
) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id is None:
        await state.clear()
        await message.answer("⚠️ Сессия сброшена. Нажмите /calories или /start.")
        return

    try:
        await message.delete()
    except Exception:
        pass

    try:
        cals = parse_calories(message.text)
    except ValueError:
        await message.answer(
            "❌ <b>Неверный формат</b>\n\n"
            "Укажите калории целым числом, например: <code>500</code> или <code>1200</code>"
        )
        return

    await _add_and_confirm(message, db, tz, config, int(user_id), message.from_user.id, cals)
    await state.clear()


async def _add_and_confirm(
    message: Message,
    db: Database,
    tz: ZoneInfo,
    config: Config,
    user_id: int,
    tg_id: int,
    calories: int,
) -> None:
    now = datetime.now(tz)
    date_day = now.strftime("%Y-%m-%d")
    await queries.add_calorie_log(db, user_id, date_day, calories, now)
    total = await queries.get_calories_sum_for_day(db, user_id, date_day)
    logger.info(f"🔥 Калории добавлены: user_id={user_id}, +{calories} ккал, сегодня всего {total}")
    await message.answer(
        f"✅ <b>+{calories} ккал</b> добавлено.\n\n"
        f"📅 Сегодня всего: <b>{total}</b> ккал",
        reply_markup=main_menu_kb(config.admin_ids, tg_id).as_markup(),
    )
