from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile

from app.db.database import Database
from app.db import queries
from app.services.analytics import build_monthly_report, month_range
from app.services.discipline import calculate_discipline_score, count_scheduled_workouts
from app.utils.charts import build_weight_chart


router = Router()


async def show_report(message: Message, db: Database, tz: ZoneInfo, user_id: int, week_parity_offset: int) -> None:
    """Вспомогательная функция для показа отчета по user_id"""
    now = datetime.now(tz)
    start, _ = month_range(now)
    report = await build_monthly_report(db, user_id, start, now, week_parity_offset)

    start_weight_str = f"{report.start_weight:.1f} кг" if report.start_weight is not None else "нет данных"
    end_weight_str = f"{report.end_weight:.1f} кг" if report.end_weight is not None else "нет данных"
    diff_str = f"{report.diff:+.1f} кг" if report.diff is not None else "нет данных"
    diff_percent_str = f"{report.diff_percent:+.1f}%" if report.diff_percent is not None else "нет данных"
    
    message_text = (
        f"📊 <b>Месячный отчет</b>\n"
        f"📅 Период: {start.strftime('%d.%m.%Y')} — {now.strftime('%d.%m.%Y')}\n\n"
        f"⚖️ <b>Прогресс веса:</b>\n"
        f"   • Стартовый вес: {start_weight_str}\n"
        f"   • Текущий вес: {end_weight_str}\n"
        f"   • Изменение: {diff_str} ({diff_percent_str})\n\n"
        f"🏋️ <b>Тренировки:</b>\n"
        f"   ✅ Выполнено: {report.completed}\n"
        f"   ❌ Пропущено: {report.missed}\n\n"
        f"📈 <b>Дисциплина: {report.discipline_score:.1f}%</b>"
    )
    await message.answer(message_text)

    if report.weights:
        chart = await build_weight_chart(report.weights)
        photo = BufferedInputFile(chart, filename="weight.png")
        await message.answer_photo(photo, caption="📈 График прогресса веса")

    if report.discipline_score < 70:
        await message.answer(
            "⚠️ <b>Внимание!</b>\n\n"
            "Ваша дисциплина ниже 70%. Это зона риска.\n\n"
            "💪 Верните регулярность тренировок немедленно!\n"
            "Помните: стабильность — ключ к успеху."
        )


@router.message(Command("report"))
async def report_command(message: Message, db: Database, tz: ZoneInfo) -> None:
    if message.from_user is None:
        return
    user = await queries.get_user_by_tg_id(db, message.from_user.id)
    if not user:
        await message.answer(
            "👋 Привет!\n\n"
            "Для начала работы выполните команду /start"
        )
        return
    week_parity_offset = int(user.get("week_parity_offset") or 0)
    await show_report(message, db, tz, int(user["id"]), week_parity_offset)


async def show_stats(message: Message, db: Database, tz: ZoneInfo, user_id: int, week_parity_offset: int) -> None:
    """Вспомогательная функция для показа статистики по user_id"""
    end = datetime.now(tz)
    start = end - timedelta(days=30)
    stats = await queries.get_workout_stats(db, user_id, start, end)
    schedule = await queries.get_workout_schedule(db, user_id)
    scheduled = count_scheduled_workouts(schedule, start, end, week_parity_offset)
    score = calculate_discipline_score(stats["done"], scheduled)

    # Статистика веса
    latest_weight = await queries.get_latest_weight(db, user_id)
    weight_value = latest_weight["weight"] if latest_weight else None
    
    # Получаем вес 30 дней назад для сравнения
    weight_30_days_ago = await queries.get_first_weight_between(db, user_id, start, end)
    
    weight_text = ""
    if weight_value is not None:
        weight_str = f"{weight_value:.1f} кг"
        if weight_30_days_ago:
            old_weight = float(weight_30_days_ago["weight"])
            diff = weight_value - old_weight
            diff_str = f"{diff:+.1f} кг" if diff != 0 else "0 кг"
            weight_text = f"⚖️ <b>Вес:</b>\n   • Текущий: {weight_str}\n   • 30 дней назад: {old_weight:.1f} кг\n   • Изменение: {diff_str}"
        else:
            weight_text = f"⚖️ <b>Текущий вес:</b> {weight_str}"
    else:
        weight_text = "⚖️ <b>Вес:</b> нет данных"
    
    await message.answer(
        f"📊 <b>Статистика за 30 дней</b>\n\n"
        f"🏋️ <b>Тренировки:</b>\n"
        f"   ✅ Выполнено: {stats['done']}\n"
        f"   ❌ Пропущено: {stats['missed']}\n"
        f"   📅 Запланировано: {scheduled}\n\n"
        f"📈 <b>Дисциплина: {score:.1f}%</b>\n\n"
        f"{weight_text}"
    )

    if score < 70:
        await message.answer(
            "⚠️ <b>Внимание!</b>\n\n"
            "Дисциплина ниже 70%.\n\n"
            "💪 Стабильность — основа прогресса.\n"
            "Исправляйтесь и возвращайтесь в ритм!"
        )


@router.message(Command("stats"))
async def stats_command(message: Message, db: Database, tz: ZoneInfo) -> None:
    if message.from_user is None:
        return
    user = await queries.get_user_by_tg_id(db, message.from_user.id)
    if not user:
        await message.answer(
            "👋 Привет!\n\n"
            "Для начала работы выполните команду /start"
        )
        return
    week_parity_offset = int(user.get("week_parity_offset") or 0)
    await show_stats(message, db, tz, int(user["id"]), week_parity_offset)
