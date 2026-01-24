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
from app.db.models import ScheduleCreate
from app.scheduler import schedule_user_jobs
from app.services.discipline import compute_week_parity_offset
from app.utils.keyboards import weekdays_kb, week_parity_kb, schedule_mode_kb, main_menu_kb, time_mode_kb
from app.utils.parsing import parse_time, format_schedule


router = Router()


class ScheduleStates(StatesGroup):
    waiting_mode = State()
    waiting_days = State()
    waiting_time_mode = State()  # Одно время или разное
    waiting_time = State()  # Одно время для всех
    waiting_day_time = State()  # Время для конкретного дня
    waiting_week_parity = State()


@router.message(Command("schedule"))
async def schedule_command(message: Message, state: FSMContext, db: Database, tz: ZoneInfo) -> None:
    if message.from_user is None:
        return
    user = await queries.get_user_by_tg_id(db, message.from_user.id)
    if not user:
        await message.answer(
            "👋 Привет!\n\n"
            "Для начала работы выполните команду /start"
        )
        return
    
    # Показываем текущее расписание раздельно для четных и нечетных
    current_schedule = await queries.get_workout_schedule(db, int(user["id"]))
    
    even_schedule = [s for s in current_schedule if s.get("week_type") == "even"]
    odd_schedule = [s for s in current_schedule if s.get("week_type") == "odd"]
    any_schedule = [s for s in current_schedule if s.get("week_type") == "any"]
    
    # Формируем красиво оформленный текст с абзацами
    schedule_parts = []
    
    if even_schedule:
        formatted = format_schedule(even_schedule, include_week_type=False)
        schedule_parts.append(f"📅 <b>Четные недели:</b>\n{formatted}")
    
    if odd_schedule:
        formatted = format_schedule(odd_schedule, include_week_type=False)
        schedule_parts.append(f"📅 <b>Нечетные недели:</b>\n{formatted}")
    
    if any_schedule:
        formatted = format_schedule(any_schedule, include_week_type=False)
        schedule_parts.append(f"📅 <b>Все недели:</b>\n{formatted}")
    
    if not schedule_parts:
        schedule_text = "⚠️ Расписание не настроено"
    else:
        schedule_text = "\n\n".join(schedule_parts)
    
    await state.update_data(user_id=int(user["id"]))
    await state.set_state(ScheduleStates.waiting_mode)
    await message.answer(
        f"📋 <b>Управление расписанием</b>\n\n"
        f"{schedule_text}\n\n"
        f"<b>Выберите действие:</b>",
        reply_markup=schedule_mode_kb().as_markup(),
    )


@router.callback_query(ScheduleStates.waiting_mode, F.data.startswith("schedulemode:"))
async def schedule_mode(query, state: FSMContext, db: Database) -> None:
    if query.data is None or query.message is None:
        return
    mode = query.data.split(":")[1]
    
    if mode == "view":
        # Показываем расписание
        data = await state.get_data()
        user_id = data.get("user_id")
        if user_id:
            current_schedule = await queries.get_workout_schedule(db, int(user_id))
            even_schedule = [s for s in current_schedule if s.get("week_type") == "even"]
            odd_schedule = [s for s in current_schedule if s.get("week_type") == "odd"]
            any_schedule = [s for s in current_schedule if s.get("week_type") == "any"]
            
            # Формируем красиво оформленный текст с абзацами
            schedule_parts = []
            
            if even_schedule:
                formatted = format_schedule(even_schedule, include_week_type=False)
                schedule_parts.append(f"📅 <b>Четные недели:</b>\n{formatted}")
            else:
                schedule_parts.append(f"📅 <b>Четные недели:</b>\n⚠️ не настроено")
            
            if odd_schedule:
                formatted = format_schedule(odd_schedule, include_week_type=False)
                schedule_parts.append(f"📅 <b>Нечетные недели:</b>\n{formatted}")
            else:
                schedule_parts.append(f"📅 <b>Нечетные недели:</b>\n⚠️ не настроено")
            
            if any_schedule:
                formatted = format_schedule(any_schedule, include_week_type=False)
                schedule_parts.append(f"📅 <b>Все недели:</b>\n{formatted}")
            
            schedule_text = "\n\n".join(schedule_parts)
            
            await query.message.edit_text(
                f"📋 <b>Ваше расписание</b>\n\n{schedule_text}",
                reply_markup=main_menu_kb().as_markup(),
            )
            await query.answer()
            await state.clear()
        return
    
    if mode not in {"even", "odd", "any"}:
        await query.answer("❌ Неверный выбор", show_alert=True)
        return
    
    # Показываем текущее расписание для этого типа недель
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id:
        current_schedule = await queries.get_workout_schedule(db, int(user_id))
        current_for_type = [s for s in current_schedule if s.get("week_type") == mode]
        if current_for_type:
            current_formatted = format_schedule(current_for_type)
            week_type_label = "четных" if mode == "even" else "нечетных" if mode == "odd" else "всех"
            await query.message.edit_text(
                f"📅 <b>Текущее расписание для {week_type_label} недель:</b>\n{current_formatted}\n\n"
                "⚠️ <b>Внимание!</b> При настройке новое расписание заменит текущее.\n\n"
                "📅 <b>Выберите дни тренировок</b>\n"
                "Нажимайте на дни для выбора, затем нажмите \"Готово\".",
                reply_markup=weekdays_kb([]).as_markup(),
            )
        else:
            week_type_text = {
                "even": "четных недель",
                "odd": "нечетных недель",
                "any": "всех недель"
            }.get(mode, "недель")
            await query.message.edit_text(
                f"📅 <b>Настройка расписания для {week_type_text}</b>\n\n"
                "📅 <b>Выберите дни тренировок</b>\n"
                "Нажимайте на дни для выбора, затем нажмите \"Готово\".",
                reply_markup=weekdays_kb([]).as_markup(),
            )
    else:
        week_type_text = {
            "even": "четных недель",
            "odd": "нечетных недель",
            "any": "всех недель"
        }.get(mode, "недель")
        await query.message.edit_text(
            f"📅 <b>Настройка расписания для {week_type_text}</b>\n\n"
            "📅 <b>Выберите дни тренировок</b>\n"
            "Нажимайте на дни для выбора, затем нажмите \"Готово\".",
            reply_markup=weekdays_kb([]).as_markup(),
        )
    
    await state.update_data(week_type=mode, days=[])
    await state.set_state(ScheduleStates.waiting_days)
    await query.answer()




@router.callback_query(ScheduleStates.waiting_days, F.data.startswith("days:"))
async def schedule_days(query, state: FSMContext) -> None:
    if query.data is None or query.message is None:
        return
    data = await state.get_data()
    selected_days = list(data.get("days", []))
    action = query.data.split(":")[1]

    if action == "toggle":
        day = int(query.data.split(":")[2])
        if day in selected_days:
            selected_days.remove(day)
        else:
            selected_days.append(day)
        selected_days = sorted(set(selected_days))
        await state.update_data(days=selected_days)
        await query.message.edit_reply_markup(reply_markup=weekdays_kb(selected_days).as_markup())
        await query.answer()
        return

    if action == "reset":
        await state.update_data(days=[])
        await query.message.edit_reply_markup(reply_markup=weekdays_kb([]).as_markup())
        await query.answer("✅ Выбор очищен")
        return

    if action == "done":
        if not selected_days:
            await query.answer("⚠️ Пожалуйста, выберите хотя бы один день", show_alert=True)
            return
        await state.set_state(ScheduleStates.waiting_time_mode)
        selected_days_text = ", ".join(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d] for d in sorted(selected_days))
        await query.message.edit_text(
            f"✅ <b>Выбраны дни:</b> {selected_days_text}\n\n"
            "⏰ <b>Выберите режим настройки времени:</b>",
            reply_markup=time_mode_kb().as_markup(),
        )
        await query.answer()


@router.callback_query(ScheduleStates.waiting_time_mode, F.data.startswith("timemode:"))
async def schedule_time_mode(query, state: FSMContext) -> None:
    if query.data is None or query.message is None:
        return
    time_mode = query.data.split(":")[1]
    data = await state.get_data()
    days = data.get("days", [])
    
    if time_mode == "single":
        # Одно время для всех дней
        await state.set_state(ScheduleStates.waiting_time)
        selected_days_text = ", ".join(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d] for d in sorted(days))
        await query.message.edit_text(
            f"✅ <b>Выбраны дни:</b> {selected_days_text}\n\n"
            "⏰ <b>Укажите время тренировки</b>\n"
            "Формат: <code>HH:MM</code>\n"
            "Пример: <code>19:30</code>",
            reply_markup=None,
        )
        await query.answer()
    elif time_mode == "multiple":
        # Разное время для каждого дня
        await state.update_data(day_times={}, current_day_index=0)
        await state.set_state(ScheduleStates.waiting_day_time)
        first_day = sorted(days)[0]
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][first_day]
        await query.message.edit_text(
            f"⏰ <b>Настройка времени для каждого дня</b>\n\n"
            f"📅 День <b>1 из {len(days)}</b>: <b>{day_name}</b>\n\n"
            "Укажите время тренировки:\n"
            "Формат: <code>HH:MM</code>\n"
            "Пример: <code>19:30</code>",
            reply_markup=None,
        )
        await query.answer()
    else:
        await query.answer("❌ Неверный выбор", show_alert=True)


@router.message(ScheduleStates.waiting_time)
async def schedule_time(
    message: Message,
    state: FSMContext,
    db: Database,
    scheduler,
    tz: ZoneInfo,
) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    days = data.get("days", [])
    week_type = data.get("week_type", "any")
    if user_id is None:
        await state.clear()
        await message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /schedule для настройки расписания."
        )
        return
    try:
        time_str = parse_time(message.text)
    except ValueError:
        await message.answer(
            "❌ <b>Неверный формат времени</b>\n\n"
            "Пожалуйста, укажите время в формате:\n"
            "<code>HH:MM</code>\n\n"
            "Примеры:\n"
            "• <code>19:30</code>\n"
            "• <code>08:00</code>\n"
            "• <code>20:15</code>"
        )
        return

    # Если это "any" (все недели), не нужно спрашивать про четность
    if week_type == "any":
        await queries.update_week_parity_offset(db, int(user_id), 0)
        # Удаляем старое расписание для этого типа недель
        await db.execute(
            "DELETE FROM workout_schedule WHERE user_id = ? AND week_type = ?;",
            (int(user_id), "any")
        )
        schedules = [
            ScheduleCreate(user_id=int(user_id), weekday=day, time=time_str, week_type=week_type)
            for day in days
        ]
        for entry in schedules:
            await queries.add_workout_schedule(db, entry)
    else:
        # Для четных/нечетных нужно знать текущую неделю для синхронизации
        await state.update_data(time_str=time_str)
        await state.set_state(ScheduleStates.waiting_week_parity)
        week_type_text = "четных" if week_type == "even" else "нечетных"
        await message.answer(
            f"📅 <b>Настройка расписания для {week_type_text} недель</b>\n\n"
            "📆 <b>Какая сейчас неделя по вашему графику?</b>\n"
            "(Это нужно для правильной синхронизации)",
            reply_markup=week_parity_kb().as_markup(),
        )
        return
    
    # Сохраняем расписание для "any"
    schedule = await queries.get_workout_schedule(db, int(user_id))
    schedule_user_jobs(
        scheduler,
        db,
        message.bot,
        int(user_id),
        message.from_user.id,
        schedule,
        0,
        tz,
    )
    await state.clear()
    
    # Показываем обновленное расписание
    even_schedule = [s for s in schedule if s.get("week_type") == "even"]
    odd_schedule = [s for s in schedule if s.get("week_type") == "odd"]
    any_schedule = [s for s in schedule if s.get("week_type") == "any"]
    
    # Формируем красиво оформленный текст с абзацами
    schedule_parts = []
    
    if even_schedule:
        formatted = format_schedule(even_schedule, include_week_type=False)
        schedule_parts.append(f"📅 <b>Четные недели:</b>\n{formatted}")
    
    if odd_schedule:
        formatted = format_schedule(odd_schedule, include_week_type=False)
        schedule_parts.append(f"📅 <b>Нечетные недели:</b>\n{formatted}")
    
    if any_schedule:
        formatted = format_schedule(any_schedule, include_week_type=False)
        schedule_parts.append(f"📅 <b>Все недели:</b>\n{formatted}")
    
    schedule_text = "\n\n".join(schedule_parts) if schedule_parts else "⚠️ Расписание не настроено"
    
    await message.answer(
        f"✅ <b>Расписание обновлено!</b>\n\n{schedule_text}",
        reply_markup=main_menu_kb().as_markup(),
    )


@router.message(ScheduleStates.waiting_day_time)
async def schedule_day_time(
    message: Message,
    state: FSMContext,
    db: Database,
    scheduler,
    tz: ZoneInfo,
) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    days = sorted(data.get("days", []))
    week_type = data.get("week_type", "any")
    day_times = data.get("day_times", {})
    current_day_index = data.get("current_day_index", 0)
    
    if user_id is None or not days:
        await state.clear()
        await message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /schedule для настройки расписания."
        )
        return
    
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass
    
    try:
        time_str = parse_time(message.text)
    except ValueError:
        await message.answer(
            "❌ <b>Неверный формат времени</b>\n\n"
            "Пожалуйста, укажите время в формате:\n"
            "<code>HH:MM</code>\n\n"
            "Примеры:\n"
            "• <code>19:30</code>\n"
            "• <code>08:00</code>\n"
            "• <code>20:15</code>"
        )
        return
    
    # Сохраняем время для текущего дня
    current_day = days[current_day_index]
    day_times[current_day] = time_str
    await state.update_data(day_times=day_times)
    
    # Переходим к следующему дню
    next_index = current_day_index + 1
    if next_index < len(days):
        await state.update_data(current_day_index=next_index)
        next_day = days[next_index]
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][next_day]
        last_bot_message_id = data.get("last_bot_message_id")
        text = (
            f"✅ <b>Время для {['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][current_day]} сохранено:</b> {time_str}\n\n"
            f"📅 День <b>{next_index + 1} из {len(days)}</b>: <b>{day_name}</b>\n\n"
            "⏰ <b>Укажите время тренировки</b>\n"
            "Формат: <code>HH:MM</code>\n"
            "Пример: <code>19:30</code>"
        )
        # Редактируем последнее сообщение бота или отправляем новое
        if last_bot_message_id:
            try:
                await message.bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=last_bot_message_id,
                    text=text,
                )
            except Exception:
                # Если не удалось отредактировать, отправляем новое
                msg = await message.answer(text)
                await state.update_data(last_bot_message_id=msg.message_id)
        else:
            msg = await message.answer(text)
            await state.update_data(last_bot_message_id=msg.message_id)
        return
    
    # Все дни настроены, сохраняем расписание
    await state.update_data(time_str="multiple")  # Маркер для множественного времени
    
    # Удаляем последнее сообщение бота, если есть
    last_bot_message_id = data.get("last_bot_message_id")
    if last_bot_message_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=last_bot_message_id)
        except Exception:
            pass
    
    # Если это "any" (все недели), не нужно спрашивать про четность
    if week_type == "any":
        await queries.update_week_parity_offset(db, int(user_id), 0)
        # Удаляем старое расписание для этого типа недель
        await db.execute(
            "DELETE FROM workout_schedule WHERE user_id = ? AND week_type = ?;",
            (int(user_id), "any")
        )
        schedules = [
            ScheduleCreate(user_id=int(user_id), weekday=day, time=day_times[day], week_type=week_type)
            for day in days
        ]
        for entry in schedules:
            await queries.add_workout_schedule(db, entry)
        
        schedule = await queries.get_workout_schedule(db, int(user_id))
        schedule_user_jobs(
            scheduler,
            db,
            message.bot,
            int(user_id),
            message.from_user.id,
            schedule,
            0,
            tz,
        )
        await state.clear()
        
        # Показываем обновленное расписание
        even_schedule = [s for s in schedule if s.get("week_type") == "even"]
        odd_schedule = [s for s in schedule if s.get("week_type") == "odd"]
        any_schedule = [s for s in schedule if s.get("week_type") == "any"]
        
        # Формируем красиво оформленный текст с абзацами
        schedule_parts = []
        
        if even_schedule:
            formatted = format_schedule(even_schedule, include_week_type=False)
            schedule_parts.append(f"📅 <b>Четные недели:</b>\n{formatted}")
        
        if odd_schedule:
            formatted = format_schedule(odd_schedule, include_week_type=False)
            schedule_parts.append(f"📅 <b>Нечетные недели:</b>\n{formatted}")
        
        if any_schedule:
            formatted = format_schedule(any_schedule, include_week_type=False)
            schedule_parts.append(f"📅 <b>Все недели:</b>\n{formatted}")
        
        schedule_text = "\n\n".join(schedule_parts) if schedule_parts else "⚠️ Расписание не настроено"
        
        await message.answer(
            f"✅ <b>Расписание обновлено!</b>\n\n{schedule_text}",
            reply_markup=main_menu_kb().as_markup(),
        )
    else:
        # Для четных/нечетных нужно знать текущую неделю для синхронизации
        await state.set_state(ScheduleStates.waiting_week_parity)
        week_type_text = "четных" if week_type == "even" else "нечетных"
        await message.answer(
            f"✅ <b>Время для всех дней сохранено!</b>\n\n"
            f"📅 <b>Настройка расписания для {week_type_text} недель</b>\n\n"
            "📆 <b>Какая сейчас неделя по вашему графику?</b>\n"
            "(Это нужно для правильной синхронизации)",
            reply_markup=week_parity_kb().as_markup(),
        )


@router.callback_query(ScheduleStates.waiting_week_parity, F.data.startswith("weekparity:"))
async def schedule_week_parity(
    query,
    state: FSMContext,
    db: Database,
    scheduler,
    tz: ZoneInfo,
) -> None:
    if query.data is None or query.message is None or query.from_user is None:
        return
    parity = query.data.split(":")[1]
    if parity not in {"even", "odd"}:
        await query.answer("❌ Неверный выбор", show_alert=True)
        return

    data = await state.get_data()
    user_id = data.get("user_id")
    days = data.get("days", [])
    time_str = data.get("time_str")
    day_times = data.get("day_times", {})
    week_type = data.get("week_type", "any")
    if user_id is None or not days:
        await state.clear()
        await query.message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /schedule для настройки расписания."
        )
        return
    
    # Проверяем, что есть либо одно время, либо множественное время
    if not time_str and not day_times:
        await state.clear()
        await query.message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /schedule для настройки расписания."
        )
        return

    is_even_week = parity == "even"
    offset = compute_week_parity_offset(datetime.now(tz), is_even_week)
    await queries.update_week_parity_offset(db, int(user_id), offset)

    # Удаляем старое расписание для этого типа недель
    await db.execute(
        "DELETE FROM workout_schedule WHERE user_id = ? AND week_type = ?;",
        (int(user_id), week_type)
    )
    
    # Добавляем новое расписание
    if day_times:
        # Множественное время для разных дней
        schedules = [
            ScheduleCreate(user_id=int(user_id), weekday=day, time=day_times[day], week_type=week_type)
            for day in days if day in day_times
        ]
    else:
        # Одно время для всех дней
        schedules = [
            ScheduleCreate(user_id=int(user_id), weekday=day, time=time_str, week_type=week_type)
            for day in days
        ]
    for entry in schedules:
        await queries.add_workout_schedule(db, entry)

    schedule = await queries.get_workout_schedule(db, int(user_id))
    schedule_user_jobs(
        scheduler,
        db,
        query.bot,
        int(user_id),
        query.from_user.id,
        schedule,
        offset,
        tz,
    )

    await state.clear()
    
    # Показываем обновленное расписание
    even_schedule = [s for s in schedule if s.get("week_type") == "even"]
    odd_schedule = [s for s in schedule if s.get("week_type") == "odd"]
    any_schedule = [s for s in schedule if s.get("week_type") == "any"]
    
    # Формируем красиво оформленный текст с абзацами
    schedule_parts = []
    
    if even_schedule:
        formatted = format_schedule(even_schedule, include_week_type=False)
        schedule_parts.append(f"📅 <b>Четные недели:</b>\n{formatted}")
    
    if odd_schedule:
        formatted = format_schedule(odd_schedule, include_week_type=False)
        schedule_parts.append(f"📅 <b>Нечетные недели:</b>\n{formatted}")
    
    if any_schedule:
        formatted = format_schedule(any_schedule, include_week_type=False)
        schedule_parts.append(f"📅 <b>Все недели:</b>\n{formatted}")
    
    schedule_text = "\n\n".join(schedule_parts) if schedule_parts else "⚠️ Расписание не настроено"
    
    await query.message.edit_reply_markup(reply_markup=None)
    await query.message.answer(
        f"✅ <b>Расписание обновлено!</b>\n\n{schedule_text}",
        reply_markup=main_menu_kb().as_markup(),
    )
    await query.answer()
