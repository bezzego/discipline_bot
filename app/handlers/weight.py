from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

logger = logging.getLogger(__name__)

from app.db.database import Database
from app.db import queries
from app.db.models import WeightEntry
from app.handlers.calories import CalorieStates
from app.utils.keyboards import main_menu_kb
from app.utils.parsing import parse_weight


router = Router()


class WeightStates(StatesGroup):
    waiting_weight = State()


async def _save_weight(db: Database, user_id: int, weight: float, tz: ZoneInfo) -> None:
    entry = WeightEntry(user_id=user_id, weight=weight, date=datetime.now(tz))
    await queries.add_weight_entry(db, entry)
    logger.info(f"⚖️ Вес сохранен: user_id={user_id}, weight={weight:.1f} кг, date={entry.date.strftime('%Y-%m-%d %H:%M:%S')}")


@router.message(Command("weight"))
async def weight_command(message: Message, state: FSMContext, db: Database, tz: ZoneInfo) -> None:
    if message.from_user is None:
        return
    user = await queries.get_user_by_tg_id(db, message.from_user.id)
    if not user:
        await message.answer(
            "👋 Привет!\n\n"
            "Для начала работы выполните команду /start"
        )
        return

    parts = message.text.split(maxsplit=1) if message.text else []
    if len(parts) > 1:
        try:
            weight = parse_weight(parts[1])
        except ValueError:
            await message.answer(
                "❌ <b>Неверный формат веса</b>\n\n"
                "Пожалуйста, укажите вес числом:\n\n"
                "Примеры:\n"
                "• <code>82.4</code>\n"
                "• <code>75</code>\n"
                "• <code>90.5</code>"
            )
            return
        await _save_weight(db, int(user["id"]), weight, tz)
        await message.answer(
            f"✅ <b>Вес сохранен!</b>\n\n"
            f"⚖️ Текущий вес: <b>{weight} кг</b>",
            reply_markup=main_menu_kb().as_markup()
        )
        return

    await state.set_state(WeightStates.waiting_weight)
    await message.answer(
        "⚖️ <b>Введите текущий вес</b>\n\n"
        "Укажите вес в килограммах одним числом.\n\n"
        "Примеры:\n"
        "• <code>82.4</code>\n"
        "• <code>75</code>\n"
        "• <code>90.5</code>"
    )


@router.message(WeightStates.waiting_weight)
async def weight_input(message: Message, state: FSMContext, db: Database, tz: ZoneInfo) -> None:
    if message.from_user is None or message.text is None:
        return
    user = await queries.get_user_by_tg_id(db, message.from_user.id)
    if not user:
        await message.answer(
            "👋 Привет!\n\n"
            "Для начала работы выполните команду /start"
        )
        await state.clear()
        return

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass

    try:
        weight = parse_weight(message.text)
    except ValueError:
        await message.answer(
            "❌ <b>Неверный формат веса</b>\n\n"
            "Пожалуйста, укажите вес числом:\n\n"
            "Примеры:\n"
            "• <code>82.4</code>\n"
            "• <code>75</code>\n"
            "• <code>90.5</code>"
        )
        return

    await _save_weight(db, int(user["id"]), weight, tz)
    await state.clear()
    await message.answer(
        f"✅ <b>Вес сохранен!</b>\n\n"
        f"⚖️ Текущий вес: <b>{weight} кг</b>",
        reply_markup=main_menu_kb().as_markup()
    )


@router.message(F.text.regexp(r"^\\s*\\d"))
async def weight_fallback(message: Message, state: FSMContext, db: Database, tz: ZoneInfo) -> None:
    """
    Fallback обработчик для автоматического сохранения веса.
    Работает даже если пользователь в другом состоянии FSM, если сообщение похоже на вес.
    """
    if message.text is None or message.from_user is None:
        return
    current = await state.get_state() or ""
    if "CalorieStates" in current and "waiting_calories" in current:
        return

    # Проверяем, что сообщение похоже на вес (число с точкой или запятой, возможно с пробелами)
    text = message.text.strip()
    # Удаляем точку или запятую (для десятичных чисел) и проверяем, что остальное - цифры
    cleaned = text.replace(".", "").replace(",", "").replace(" ", "")
    if not cleaned.isdigit() or len(cleaned) == 0:
        return
    
    try:
        weight = parse_weight(text)
    except ValueError:
        return

    user = await queries.get_user_by_tg_id(db, message.from_user.id)
    if not user:
        return
    
    # Сохраняем вес независимо от состояния FSM
    await _save_weight(db, int(user["id"]), weight, tz)
    await message.answer(
        f"✅ <b>Вес сохранен!</b>\n\n"
        f"⚖️ Текущий вес: <b>{weight} кг</b>",
        reply_markup=main_menu_kb().as_markup()
    )
