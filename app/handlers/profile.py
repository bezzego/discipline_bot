from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import Config
from app.db.database import Database
from app.db import queries
from app.services.discipline import is_user_week_even
from app.utils.keyboards import main_menu_kb
from app.utils.parsing import format_schedule


router = Router()


async def build_profile_text(db: Database, user_id: int, tz: ZoneInfo) -> str:
    user_row = await db.fetch_one("SELECT * FROM users WHERE id = ?;", (user_id,))
    user = dict(user_row) if user_row else {}
    target_weight = user.get("target_weight")
    week_parity_offset = user.get("week_parity_offset")

    schedule = await queries.get_workout_schedule(db, user_id)
    latest_weight = await queries.get_latest_weight(db, user_id)
    current_weight = latest_weight["weight"] if latest_weight else "нет данных"

    week_parity_text = "не задана"
    if week_parity_offset is not None:
        even_now = is_user_week_even(datetime.now(tz), int(week_parity_offset))
        week_parity_text = "четная" if even_now else "нечетная"

    # Разделяем расписание по типам недель
    even_schedule = [s for s in schedule if s.get("week_type") == "even"]
    odd_schedule = [s for s in schedule if s.get("week_type") == "odd"]
    any_schedule = [s for s in schedule if s.get("week_type") == "any"]
    
    schedule_text = ""
    if even_schedule:
        schedule_text += f"📅 Четные недели: {format_schedule(even_schedule)}\n"
    if odd_schedule:
        schedule_text += f"📅 Нечетные недели: {format_schedule(odd_schedule)}\n"
    if any_schedule:
        schedule_text += f"📅 Все недели: {format_schedule(any_schedule)}\n"
    if not schedule_text:
        schedule_text = "не настроено\n"
    
    target_weight_str = f"{target_weight:.1f} кг" if target_weight is not None else "не задан"
    current_weight_str = f"{current_weight:.1f} кг" if isinstance(current_weight, (int, float)) else current_weight
    
    return (
        "📊 <b>Профиль</b>\n\n"
        f"🎯 <b>Целевой вес:</b> {target_weight_str}\n"
        f"⚖️ <b>Текущий вес:</b> {current_weight_str}\n\n"
        f"📅 <b>Расписание:</b>\n{schedule_text}\n"
        f"📆 <b>Текущая неделя:</b> {week_parity_text}"
    )


async def show_profile(message: Message, db: Database, tz: ZoneInfo, user_id: int, config: Config = None) -> None:
    """Вспомогательная функция для показа профиля по user_id"""
    text = await build_profile_text(db, user_id, tz)
    admin_ids = config.admin_ids if config else None
    user_tg_id = message.from_user.id if message.from_user else None
    await message.answer(text, reply_markup=main_menu_kb(admin_ids, user_tg_id).as_markup())


@router.message(Command("profile"))
async def profile_command(message: Message, db: Database, tz: ZoneInfo, config: Config) -> None:
    if message.from_user is None:
        return
    user = await queries.get_user_by_tg_id(db, message.from_user.id)
    if not user:
        await message.answer(
            "👋 Привет!\n\n"
            "Для начала работы выполните команду /start"
        )
        return
    await show_profile(message, db, tz, int(user["id"]))
