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
from app.services.calories import compute_calorie_profile
from app.utils.keyboards import main_menu_kb
from app.utils.parsing import format_schedule


router = Router()

GOAL_LABELS = {"lose": "похудение", "maintain": "удержание", "gain": "набор массы"}


async def build_profile_text(db: Database, user_id: int, tz: ZoneInfo) -> str:
    user_row = await db.fetch_one("SELECT * FROM users WHERE id = ?;", (user_id,))
    user = dict(user_row) if user_row else {}
    target_weight = user.get("target_weight")
    week_parity_offset = user.get("week_parity_offset")
    height_cm = user.get("height_cm")
    birth_year = user.get("birth_year")
    gender = user.get("gender")
    activity_level = user.get("activity_level")
    goal = user.get("goal")

    schedule = await queries.get_workout_schedule(db, user_id)
    latest_weight = await queries.get_latest_weight(db, user_id)
    current_weight_val = latest_weight["weight"] if latest_weight else None
    current_weight_str = f"{current_weight_val:.1f} кг" if isinstance(current_weight_val, (int, float)) else "нет данных"

    week_parity_text = "не задана"
    if week_parity_offset is not None:
        even_now = is_user_week_even(datetime.now(tz), int(week_parity_offset))
        week_parity_text = "четная" if even_now else "нечетная"

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

    parts = [
        "📊 <b>Профиль</b>\n",
        f"🎯 <b>Целевой вес:</b> {target_weight_str}",
        f"⚖️ <b>Текущий вес:</b> {current_weight_str}",
    ]

    # Калории, ИМТ, цель — считаем по текущему весу
    if current_weight_val and height_cm and birth_year and gender:
        cp = compute_calorie_profile(
            weight_kg=current_weight_val,
            height_cm=height_cm,
            birth_year=birth_year,
            gender=gender,
            activity_level=activity_level,
            goal=goal,
            now=datetime.now(tz),
        )
        if cp:
            parts.append("")
            parts.append("🔥 <b>Норма калорий</b> (формула Mifflin–St Jeor)")
            parts.append(f"• Базовый обмен (в покое): <b>{int(cp.bmr)}</b> ккал")
            parts.append(f"• Суточная норма (с учётом активности): <b>{int(cp.tdee)}</b> ккал/день")
            parts.append(f"• Цель <b>{GOAL_LABELS.get(cp.goal, cp.goal)}</b> → <b>{cp.daily_target}</b> ккал/день")
            parts.append(f"• ИМТ: <b>{cp.bmi}</b> ({cp.bmi_category})")
            today = datetime.now(tz).strftime("%Y-%m-%d")
            today_cals = await queries.get_calories_sum_for_day(db, user_id, today)
            parts.append(f"• Сегодня съедено: <b>{today_cals}</b> ккал")
    else:
        parts.append("")
        parts.append("⚠️ Заполните рост, возраст и пол в /start для расчёта нормы калорий и ИМТ.")

    parts.append("")
    parts.append(f"📅 <b>Расписание:</b>\n{schedule_text}")
    parts.append(f"📆 <b>Текущая неделя:</b> {week_parity_text}")

    return "\n".join(parts)


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
    await show_profile(message, db, tz, int(user["id"]), config)
