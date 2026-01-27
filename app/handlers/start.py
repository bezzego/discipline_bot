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

from app.config import Config
from app.db.database import Database
from app.db import queries
from app.db.models import ScheduleCreate
from app.handlers.profile import build_profile_text
from app.scheduler import schedule_user_jobs
from app.services.discipline import compute_week_parity_offset
from app.utils.keyboards import (
    weekdays_kb,
    week_parity_kb,
    main_menu_kb,
    time_mode_kb,
    gender_kb,
    activity_kb,
    goal_kb,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.utils.parsing import parse_weight, parse_time, parse_height_cm, parse_birth_year, format_schedule
from app.db.models import WeightEntry
from app.services.access import has_access, PRODUCT_DESCRIPTION, get_product_price_text
from app.utils.keyboards import paywall_kb


router = Router()


class StartStates(StatesGroup):
    waiting_weight = State()
    waiting_height = State()
    waiting_birth_year = State()
    waiting_gender = State()
    waiting_activity = State()
    waiting_goal = State()
    waiting_target_weight_goal = State()
    waiting_setup_choice = State()
    waiting_even_days = State()
    waiting_even_time_mode = State()  # Режим времени для четных недель
    waiting_even_time = State()  # Одно время для всех дней четных недель
    waiting_even_day_time = State()  # Время для конкретного дня четных недель
    waiting_odd_days = State()
    waiting_odd_time_mode = State()  # Режим времени для нечетных недель
    waiting_odd_time = State()  # Одно время для всех дней нечетных недель
    waiting_odd_day_time = State()  # Время для конкретного дня нечетных недель
    waiting_any_days = State()
    waiting_any_time_mode = State()  # Режим времени для всех недель
    waiting_any_time = State()  # Одно время для всех дней всех недель
    waiting_any_day_time = State()  # Время для конкретного дня всех недель
    waiting_week_parity = State()


async def _paywall_start_text(db: Database) -> str:
    product_price = await get_product_price_text(db)
    return (
        "⏱ <b>Бесплатный период (5 дней) закончился.</b>\n\n"
        "Оформите подписку:\n\n"
        f"{PRODUCT_DESCRIPTION}\n\n"
        f"{product_price}\n\n"
        "Нажмите кнопку ниже для оплаты."
    )


@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext, db: Database, tz: ZoneInfo, config: Config) -> None:
    if message.from_user is None:
        logger.warning("⚠️ Получена команда /start без информации о пользователе")
        return

    tg_id = message.from_user.id
    username = message.from_user.username or "без username"
    logger.info(f"📥 Команда /start от пользователя: tg_id={tg_id}, username=@{username}")

    existing_user = await queries.get_user_by_tg_id(db, tg_id)
    if existing_user:
        if not await has_access(db, tg_id, existing_user, config, tz):
            logger.info(f"🔒 Доступ закрыт, paywall: tg_id={tg_id}")
            from app.services.access import get_subscription_price_rub
            price = await get_subscription_price_rub(db)
            paywall_text = await _paywall_start_text(db)
            await message.answer(paywall_text, reply_markup=paywall_kb(price=price).as_markup())
            return
        logger.info(f"ℹ️ Пользователь {tg_id} уже зарегистрирован, показываем меню")
        await message.answer(
            "👋 <b>Вы уже зарегистрированы!</b>\n\n"
            "Используйте /schedule для настройки расписания\n"
            "Используйте /profile для просмотра профиля",
            reply_markup=main_menu_kb(config.admin_ids, message.from_user.id).as_markup(),
        )
        return
    
    logger.info(f"🆕 Начало регистрации нового пользователя: tg_id={tg_id}")
    now = datetime.now(tz)
    user_id = await queries.create_user(db, tg_id, now)
    await state.update_data(user_id=user_id)
    logger.info(f"✅ Пользователь создан: user_id={user_id}, tg_id={tg_id}")
    
    await message.answer(
        "👋 <b>Добро пожаловать в Discipline Bot!</b>\n\n"
        "Помогу отслеживать тренировки, вес и норму калорий.\n\n"
        "🆓 <b>У вас 5 дней бесплатного доступа.</b> Затем — подписка. Описание и стоимость — /tariff\n\n"
        "📋 <b>Создадим профиль</b> — потребуются рост, возраст, пол, активность и цель.\n\n"
        "📝 <b>Шаг 1 из 8:</b> Укажите ваш <b>текущий вес</b> (кг)\n\n"
        "Примеры: <code>72.5</code>, <code>85</code>, <code>68</code>"
    )
    await state.set_state(StartStates.waiting_weight)




@router.message(StartStates.waiting_weight)
async def start_weight(message: Message, state: FSMContext, db: Database, tz: ZoneInfo) -> None:
    if message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id is None:
        await state.clear()
        await message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /start для начала регистрации."
        )
        return

    try:
        await message.delete()
    except Exception:
        pass

    try:
        weight = parse_weight(message.text)
    except ValueError:
        await message.answer("❌ Укажите вес числом, например: <code>72.5</code> или <code>85</code>")
        return

    await queries.update_target_weight(db, int(user_id), weight)
    await queries.add_weight_entry(db, WeightEntry(user_id=int(user_id), weight=weight, date=datetime.now(tz)))
    await state.set_state(StartStates.waiting_height)

    await message.answer(
        f"✅ <b>Вес сохранён: {weight} кг</b>\n\n"
        "📝 <b>Шаг 2 из 8:</b> Укажите <b>рост</b> (см)\n\n"
        "Примеры: <code>175</code>, <code>168</code>, <code>1.82</code> (м)"
    )


@router.message(StartStates.waiting_height)
async def start_height(message: Message, state: FSMContext, db: Database) -> None:
    if message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id is None:
        await state.clear()
        await message.answer("⚠️ Сессия сброшена. Нажмите /start.")
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        h = parse_height_cm(message.text)
    except ValueError:
        await message.answer("❌ Укажите рост в см, например: <code>175</code> или <code>1.82</code>")
        return
    await queries.update_user_calorie_params(db, int(user_id), height_cm=h)
    await state.set_state(StartStates.waiting_birth_year)
    await message.answer(
        f"✅ <b>Рост сохранён: {h} см</b>\n\n"
        "📝 <b>Шаг 3 из 8:</b> Укажите <b>год рождения</b> или <b>возраст</b>\n\n"
        "Примеры: <code>1990</code>, <code>34</code>"
    )


@router.message(StartStates.waiting_birth_year)
async def start_birth_year(message: Message, state: FSMContext, db: Database) -> None:
    if message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id is None:
        await state.clear()
        await message.answer("⚠️ Сессия сброшена. Нажмите /start.")
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        by = parse_birth_year(message.text)
    except ValueError:
        await message.answer("❌ Укажите год рождения (например <code>1990</code>) или возраст (<code>34</code>).")
        return
    await queries.update_user_calorie_params(db, int(user_id), birth_year=by)
    await state.set_state(StartStates.waiting_gender)
    await message.answer(
        f"✅ <b>Год рождения сохранён</b>\n\n"
        "📝 <b>Шаг 4 из 8:</b> Укажите <b>пол</b>",
        reply_markup=gender_kb().as_markup(),
    )


@router.callback_query(StartStates.waiting_gender, F.data.startswith("gender:"))
async def start_gender(query, state: FSMContext, db: Database) -> None:
    if query.data is None or query.message is None:
        return
    g = query.data.split(":")[1]
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id is None:
        await state.clear()
        await query.answer("⚠️ Сессия сброшена.", show_alert=True)
        return
    await queries.update_user_calorie_params(db, int(user_id), gender=g)
    await state.set_state(StartStates.waiting_activity)
    await query.message.edit_text(
        "✅ <b>Пол сохранён</b>\n\n"
        "📝 <b>Шаг 5 из 8:</b> Выберите <b>уровень активности</b>",
        reply_markup=activity_kb().as_markup(),
    )
    await query.answer()


@router.callback_query(StartStates.waiting_activity, F.data.startswith("activity:"))
async def start_activity(query, state: FSMContext, db: Database) -> None:
    if query.data is None or query.message is None:
        return
    act = query.data.split(":")[1]
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id is None:
        await state.clear()
        await query.answer("⚠️ Сессия сброшена.", show_alert=True)
        return
    await queries.update_user_calorie_params(db, int(user_id), activity_level=act)
    await state.set_state(StartStates.waiting_goal)
    await query.message.edit_text(
        "✅ <b>Активность сохранена</b>\n\n"
        "📝 <b>Шаг 6 из 8:</b> Выберите <b>цель</b>",
        reply_markup=goal_kb().as_markup(),
    )
    await query.answer()


@router.callback_query(StartStates.waiting_goal, F.data.startswith("goal:"))
async def start_goal(query, state: FSMContext, db: Database) -> None:
    if query.data is None or query.message is None:
        return
    goal = query.data.split(":")[1]
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id is None:
        await state.clear()
        await query.answer("⚠️ Сессия сброшена.", show_alert=True)
        return
    await queries.update_user_calorie_params(db, int(user_id), goal=goal)
    await state.update_data(goal=goal)

    if goal == "maintain":
        await state.set_state(StartStates.waiting_setup_choice)
        builder = InlineKeyboardBuilder()
        builder.button(text="Настроить разные расписания для четных и нечетных недель", callback_data="setup:separate")
        builder.button(text="Одно расписание для всех недель", callback_data="setup:any")
        builder.button(text="Пропустить (настрою позже)", callback_data="setup:skip")
        builder.adjust(1, 1, 1)
        await query.message.edit_text(
            "✅ <b>Цель сохранена</b>\n\n"
            "📝 <b>Шаг 8 из 8: Настройка расписания</b>\n\n"
            "Выберите вариант:\n\n"
            "🔀 <b>Разные расписания</b> — для четных и нечетных недель\n\n"
            "📅 <b>Одно расписание</b> — для всех недель\n\n"
            "⏭️ <b>Пропустить</b> — настроите позже через /schedule",
            reply_markup=builder.as_markup(),
        )
        await query.answer()
        return

    await state.set_state(StartStates.waiting_target_weight_goal)
    label = "похудения" if goal == "lose" else "набора массы"
    await query.message.edit_text(
        f"✅ <b>Цель сохранена</b>\n\n"
        f"📝 <b>Шаг 7 из 8:</b> Укажите <b>целевой вес</b> для {label} (кг)\n\n"
        "Примеры: <code>75</code>, <code>82</code>",
        reply_markup=None,
    )
    await query.answer()


@router.message(StartStates.waiting_target_weight_goal)
async def start_target_weight_goal(message: Message, state: FSMContext, db: Database) -> None:
    if message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    if user_id is None:
        await state.clear()
        await message.answer("⚠️ Сессия сброшена. Нажмите /start.")
        return
    try:
        await message.delete()
    except Exception:
        pass
    try:
        tw = parse_weight(message.text)
    except ValueError:
        await message.answer("❌ Укажите вес числом, например: <code>75</code> или <code>82</code>")
        return
    await queries.update_user_calorie_params(db, int(user_id), target_weight=tw)
    await state.set_state(StartStates.waiting_setup_choice)
    builder = InlineKeyboardBuilder()
    builder.button(text="Настроить разные расписания для четных и нечетных недель", callback_data="setup:separate")
    builder.button(text="Одно расписание для всех недель", callback_data="setup:any")
    builder.button(text="Пропустить (настрою позже)", callback_data="setup:skip")
    builder.adjust(1, 1, 1)
    await message.answer(
        f"✅ <b>Целевой вес сохранён: {tw} кг</b>\n\n"
        "📝 <b>Шаг 8 из 8: Настройка расписания</b>\n\n"
        "Выберите вариант:\n\n"
        "🔀 <b>Разные расписания</b> — для четных и нечетных недель\n\n"
        "📅 <b>Одно расписание</b> — для всех недель\n\n"
        "⏭️ <b>Пропустить</b> — настроите позже через /schedule",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(StartStates.waiting_setup_choice, F.data.startswith("setup:"))
async def start_setup_choice(query, state: FSMContext, config: Config) -> None:
    if query.data is None or query.message is None or query.from_user is None:
        return
    setup_type = query.data.split(":")[1]

    if setup_type == "skip":
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.answer(
            "✅ <b>Регистрация завершена!</b>\n\n"
            "Настройте расписание через /schedule, профиль — /profile.",
            reply_markup=main_menu_kb(config.admin_ids, query.from_user.id).as_markup(),
        )
        await query.answer()
        await state.clear()
        return
    
    if setup_type == "any":
        await state.update_data(setup_type="any", days=[])
        await state.set_state(StartStates.waiting_any_days)
        await query.message.edit_text(
            "📅 <b>Настройка расписания для всех недель</b>\n\n"
            "📅 <b>Выберите дни тренировок</b>\n"
            "Нажимайте на дни для выбора, затем нажмите \"Готово\".",
            reply_markup=weekdays_kb([]).as_markup(),
        )
        await query.answer()
        return
    
    if setup_type == "separate":
        await state.update_data(setup_type="separate", even_days=[], odd_days=[])
        await state.set_state(StartStates.waiting_even_days)
        await query.message.edit_text(
            "📅 <b>Настройка расписания для ЧЕТНЫХ недель</b>\n\n"
            "📅 <b>Выберите дни тренировок</b>\n"
            "Нажимайте на дни для выбора, затем нажмите \"Готово\".",
            reply_markup=weekdays_kb([]).as_markup(),
        )
        await query.answer()
        return


@router.callback_query(StartStates.waiting_even_days, F.data.startswith("days:"))
async def start_even_days(query, state: FSMContext) -> None:
    if query.data is None or query.message is None:
        return
    data = await state.get_data()
    selected_days = list(data.get("even_days", []))
    action = query.data.split(":")[1]

    if action == "toggle":
        day = int(query.data.split(":")[2])
        if day in selected_days:
            selected_days.remove(day)
        else:
            selected_days.append(day)
        selected_days = sorted(set(selected_days))
        await state.update_data(even_days=selected_days)
        await query.message.edit_reply_markup(reply_markup=weekdays_kb(selected_days).as_markup())
        await query.answer()
        return

    if action == "reset":
        await state.update_data(even_days=[])
        await query.message.edit_reply_markup(reply_markup=weekdays_kb([]).as_markup())
        await query.answer("✅ Выбор очищен")
        return

    if action == "done":
        if not selected_days:
            await query.answer("⚠️ Пожалуйста, выберите хотя бы один день", show_alert=True)
            return
        await state.set_state(StartStates.waiting_even_time_mode)
        selected_days_text = ", ".join(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d] for d in sorted(selected_days))
        await query.message.edit_text(
            f"📅 <b>Четные недели</b>\n"
            f"✅ Выбраны дни: <b>{selected_days_text}</b>\n\n"
            "⏰ <b>Выберите режим настройки времени:</b>",
            reply_markup=time_mode_kb().as_markup(),
        )
        await query.answer()


@router.callback_query(StartStates.waiting_even_time_mode, F.data.startswith("timemode:"))
async def start_even_time_mode(query, state: FSMContext) -> None:
    if query.data is None or query.message is None:
        return
    time_mode = query.data.split(":")[1]
    data = await state.get_data()
    even_days = data.get("even_days", [])
    
    if time_mode == "single":
        # Одно время для всех дней
        await state.update_data(even_time_mode="single")
        await state.set_state(StartStates.waiting_even_time)
        selected_days_text = ", ".join(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d] for d in sorted(even_days))
        await query.message.edit_text(
            f"📅 <b>Четные недели</b>\n"
            f"✅ Выбраны дни: <b>{selected_days_text}</b>\n\n"
            "⏰ <b>Укажите время тренировки</b>\n"
            "Формат: <code>HH:MM</code>\n"
            "Пример: <code>19:30</code>",
            reply_markup=None,
        )
        await query.answer()
    elif time_mode == "multiple":
        # Разное время для каждого дня
        first_day = sorted(even_days)[0]
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][first_day]
        msg = await query.message.edit_text(
            f"⏰ <b>Настройка времени для каждого дня (четные недели)</b>\n\n"
            f"📅 День <b>1 из {len(even_days)}</b>: <b>{day_name}</b>\n\n"
            "Укажите время тренировки:\n"
            "Формат: <code>HH:MM</code>\n"
            "Пример: <code>19:30</code>",
            reply_markup=None,
        )
        await state.update_data(even_time_mode="multiple", even_day_times={}, even_current_day_index=0, even_last_bot_message_id=msg.message_id)
        await state.set_state(StartStates.waiting_even_day_time)
        await query.answer()
    else:
        await query.answer("❌ Неверный выбор", show_alert=True)


@router.message(StartStates.waiting_even_time)
async def start_even_time(message: Message, state: FSMContext, db: Database, scheduler, tz: ZoneInfo) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    even_days = data.get("even_days", [])
    if user_id is None:
        await state.clear()
        await message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /start для начала регистрации."
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

    await state.update_data(even_time=time_str, odd_days=[])
    await state.set_state(StartStates.waiting_odd_days)
    await message.answer(
        f"✅ <b>Расписание для четных недель сохранено:</b>\n"
        f"{', '.join(['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][d] for d in sorted(even_days))} в <b>{time_str}</b>\n\n"
        "📅 <b>Теперь настройте расписание для НЕЧЕТНЫХ недель</b>\n\n"
        "📅 <b>Выберите дни тренировок</b>\n"
        "Нажимайте на дни для выбора, затем нажмите \"Готово\".",
        reply_markup=weekdays_kb([]).as_markup(),
    )


@router.message(StartStates.waiting_even_day_time)
async def start_even_day_time(message: Message, state: FSMContext, db: Database, scheduler, tz: ZoneInfo) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    even_days = sorted(data.get("even_days", []))
    even_day_times = data.get("even_day_times", {})
    current_day_index = data.get("even_current_day_index", 0)
    last_bot_message_id = data.get("even_last_bot_message_id")
    
    if user_id is None or not even_days:
        await state.clear()
        await message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /start для начала регистрации."
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
    current_day = even_days[current_day_index]
    even_day_times[current_day] = time_str
    await state.update_data(even_day_times=even_day_times)
    
    # Переходим к следующему дню
    next_index = current_day_index + 1
    if next_index < len(even_days):
        await state.update_data(even_current_day_index=next_index)
        next_day = even_days[next_index]
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][next_day]
        text = (
            f"✅ <b>Время для {['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][current_day]} сохранено:</b> {time_str}\n\n"
            f"📅 День <b>{next_index + 1} из {len(even_days)}</b>: <b>{day_name}</b>\n\n"
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
                await state.update_data(even_last_bot_message_id=msg.message_id)
        else:
            msg = await message.answer(text)
            await state.update_data(even_last_bot_message_id=msg.message_id)
        return
    
    # Все дни настроены, переходим к нечетным неделям
    await state.update_data(even_time_mode="multiple", odd_days=[])
    await state.set_state(StartStates.waiting_odd_days)
    schedule_text = ", ".join([f"{['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][d]} {even_day_times[d]}" for d in sorted(even_days)])
    # Удаляем последнее сообщение бота, если есть
    if last_bot_message_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=last_bot_message_id)
        except Exception:
            pass
    await message.answer(
        f"✅ <b>Расписание для четных недель сохранено:</b>\n{schedule_text}\n\n"
        "📅 <b>Теперь настройте расписание для НЕЧЕТНЫХ недель</b>\n\n"
        "📅 <b>Выберите дни тренировок</b>\n"
        "Нажимайте на дни для выбора, затем нажмите \"Готово\".",
        reply_markup=weekdays_kb([]).as_markup(),
    )


@router.callback_query(StartStates.waiting_odd_days, F.data.startswith("days:"))
async def start_odd_days(query, state: FSMContext) -> None:
    if query.data is None or query.message is None:
        return
    data = await state.get_data()
    selected_days = list(data.get("odd_days", []))
    action = query.data.split(":")[1]

    if action == "toggle":
        day = int(query.data.split(":")[2])
        if day in selected_days:
            selected_days.remove(day)
        else:
            selected_days.append(day)
        selected_days = sorted(set(selected_days))
        await state.update_data(odd_days=selected_days)
        await query.message.edit_reply_markup(reply_markup=weekdays_kb(selected_days).as_markup())
        await query.answer()
        return

    if action == "reset":
        await state.update_data(odd_days=[])
        await query.message.edit_reply_markup(reply_markup=weekdays_kb([]).as_markup())
        await query.answer("✅ Выбор очищен")
        return

    if action == "done":
        if not selected_days:
            await query.answer("⚠️ Пожалуйста, выберите хотя бы один день", show_alert=True)
            return
        await state.set_state(StartStates.waiting_odd_time_mode)
        selected_days_text = ", ".join(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d] for d in sorted(selected_days))
        await query.message.edit_text(
            f"📅 <b>Настройка расписания для НЕЧЕТНЫХ недель</b>\n"
            f"✅ Выбраны дни: <b>{selected_days_text}</b>\n\n"
            "⏰ <b>Выберите режим настройки времени:</b>",
            reply_markup=time_mode_kb().as_markup(),
        )
        await query.answer()


@router.callback_query(StartStates.waiting_odd_time_mode, F.data.startswith("timemode:"))
async def start_odd_time_mode(query, state: FSMContext) -> None:
    if query.data is None or query.message is None:
        return
    time_mode = query.data.split(":")[1]
    data = await state.get_data()
    odd_days = data.get("odd_days", [])
    
    if time_mode == "single":
        # Одно время для всех дней
        await state.set_state(StartStates.waiting_odd_time)
        selected_days_text = ", ".join(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d] for d in sorted(odd_days))
        await query.message.edit_text(
            f"📅 <b>Настройка расписания для НЕЧЕТНЫХ недель</b>\n"
            f"✅ Выбраны дни: <b>{selected_days_text}</b>\n\n"
            "⏰ <b>Укажите время тренировки</b>\n"
            "Формат: <code>HH:MM</code>\n"
            "Пример: <code>19:30</code>",
            reply_markup=None,
        )
        await query.answer()
    elif time_mode == "multiple":
        # Разное время для каждого дня
        first_day = sorted(odd_days)[0]
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][first_day]
        msg = await query.message.edit_text(
            f"⏰ <b>Настройка времени для каждого дня (нечетные недели)</b>\n\n"
            f"📅 День <b>1 из {len(odd_days)}</b>: <b>{day_name}</b>\n\n"
            "Укажите время тренировки:\n"
            "Формат: <code>HH:MM</code>\n"
            "Пример: <code>19:30</code>",
            reply_markup=None,
        )
        await state.update_data(odd_day_times={}, odd_current_day_index=0, odd_last_bot_message_id=msg.message_id)
        await state.set_state(StartStates.waiting_odd_day_time)
        await query.answer()
    else:
        await query.answer("❌ Неверный выбор", show_alert=True)


@router.message(StartStates.waiting_odd_time)
async def start_odd_time(message: Message, state: FSMContext, db: Database, scheduler, tz: ZoneInfo) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    even_days = data.get("even_days", [])
    even_time = data.get("even_time")
    even_time_mode = data.get("even_time_mode", "single")
    even_day_times = data.get("even_day_times", {})
    odd_days = data.get("odd_days", [])
    
    # Проверяем, что есть данные для четных недель (либо одно время, либо множественное)
    even_configured = False
    if even_time_mode == "single" and even_time:
        even_configured = True
    elif even_time_mode == "multiple" and even_day_times:
        even_configured = True
    
    if user_id is None or not even_configured:
        await state.clear()
        await message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /start для начала регистрации."
        )
        return
    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass
    
    try:
        odd_time = parse_time(message.text)
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

    await state.update_data(odd_time=odd_time, odd_time_mode="single")
    await state.set_state(StartStates.waiting_week_parity)
    
    # Формируем текст расписания
    even_schedule_text = ""
    if even_days:
        even_time_mode = data.get("even_time_mode", "single")
        if even_time_mode == "single" and even_time:
            even_schedule_text = f"📅 <b>Четные недели:</b> {', '.join(['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][d] for d in sorted(even_days))} в <b>{even_time}</b>\n"
        elif even_time_mode == "multiple":
            even_day_times = data.get("even_day_times", {})
            day_names = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']
            schedule_items = [f"{day_names[d]} {even_day_times.get(d, '?')}" for d in sorted(even_days)]
            even_schedule_text = f"📅 <b>Четные недели:</b> {', '.join(schedule_items)}\n"
    
    odd_schedule_text = ""
    if odd_days:
        odd_time_mode = data.get("odd_time_mode", "single")
        if odd_time_mode == "single" and odd_time:
            odd_schedule_text = f"📅 <b>Нечетные недели:</b> {', '.join(['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][d] for d in sorted(odd_days))} в <b>{odd_time}</b>\n"
        elif odd_time_mode == "multiple":
            odd_day_times = data.get("odd_day_times", {})
            day_names = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']
            schedule_items = [f"{day_names[d]} {odd_day_times.get(d, '?')}" for d in sorted(odd_days)]
            odd_schedule_text = f"📅 <b>Нечетные недели:</b> {', '.join(schedule_items)}\n"
    
    await message.answer(
        f"✅ <b>Расписание настроено:</b>\n\n"
        f"{even_schedule_text}"
        f"{odd_schedule_text}\n"
        "📆 <b>Какая сейчас неделя по вашему графику?</b>\n"
        "(Это нужно для правильной синхронизации)",
        reply_markup=week_parity_kb().as_markup(),
    )


@router.message(StartStates.waiting_odd_day_time)
async def start_odd_day_time(message: Message, state: FSMContext, db: Database, scheduler, tz: ZoneInfo) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    odd_days = sorted(data.get("odd_days", []))
    odd_day_times = data.get("odd_day_times", {})
    current_day_index = data.get("odd_current_day_index", 0)
    
    if user_id is None or not odd_days:
        await state.clear()
        await message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /start для начала регистрации."
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
    current_day = odd_days[current_day_index]
    odd_day_times[current_day] = time_str
    await state.update_data(odd_day_times=odd_day_times)
    
    # Переходим к следующему дню
    next_index = current_day_index + 1
    if next_index < len(odd_days):
        await state.update_data(odd_current_day_index=next_index)
        next_day = odd_days[next_index]
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][next_day]
        last_bot_message_id = data.get("odd_last_bot_message_id")
        text = (
            f"✅ <b>Время для {['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][current_day]} сохранено:</b> {time_str}\n\n"
            f"📅 День <b>{next_index + 1} из {len(odd_days)}</b>: <b>{day_name}</b>\n\n"
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
                await state.update_data(odd_last_bot_message_id=msg.message_id)
        else:
            msg = await message.answer(text)
            await state.update_data(odd_last_bot_message_id=msg.message_id)
        return
    
    # Все дни настроены, переходим к выбору недели
    await state.update_data(odd_time_mode="multiple")
    await state.set_state(StartStates.waiting_week_parity)
    
    # Удаляем последнее сообщение бота, если есть
    last_bot_message_id = data.get("odd_last_bot_message_id")
    if last_bot_message_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=last_bot_message_id)
        except Exception:
            pass
    
    # Формируем текст расписания
    even_schedule_text = ""
    even_days = data.get("even_days", [])
    if even_days:
        even_time_mode = data.get("even_time_mode", "single")
        if even_time_mode == "single":
            even_time = data.get("even_time")
            if even_time:
                even_schedule_text = f"📅 <b>Четные недели:</b> {', '.join(['Пн','Вт','Ср','Чт','Пт','Сб','Вс'][d] for d in sorted(even_days))} в <b>{even_time}</b>\n"
        elif even_time_mode == "multiple":
            even_day_times = data.get("even_day_times", {})
            day_names = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']
            schedule_items = [f"{day_names[d]} {even_day_times.get(d, '?')}" for d in sorted(even_days)]
            even_schedule_text = f"📅 <b>Четные недели:</b> {', '.join(schedule_items)}\n"
    
    day_names = ['Пн','Вт','Ср','Чт','Пт','Сб','Вс']
    schedule_items = [f"{day_names[d]} {odd_day_times.get(d, '?')}" for d in sorted(odd_days)]
    odd_schedule_text = f"📅 <b>Нечетные недели:</b> {', '.join(schedule_items)}\n"
    
    await message.answer(
        f"✅ <b>Расписание настроено:</b>\n\n"
        f"{even_schedule_text}"
        f"{odd_schedule_text}\n"
        "📆 <b>Какая сейчас неделя по вашему графику?</b>\n"
        "(Это нужно для правильной синхронизации)",
        reply_markup=week_parity_kb().as_markup(),
    )


@router.callback_query(StartStates.waiting_any_days, F.data.startswith("days:"))
async def start_any_days(query, state: FSMContext) -> None:
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
        await state.set_state(StartStates.waiting_any_time_mode)
        selected_days_text = ", ".join(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d] for d in sorted(selected_days))
        await query.message.edit_text(
            f"✅ <b>Выбраны дни:</b> {selected_days_text}\n\n"
            "⏰ <b>Выберите режим настройки времени:</b>",
            reply_markup=time_mode_kb().as_markup(),
        )
        await query.answer()


@router.callback_query(StartStates.waiting_any_time_mode, F.data.startswith("timemode:"))
async def start_any_time_mode(query, state: FSMContext) -> None:
    if query.data is None or query.message is None:
        return
    time_mode = query.data.split(":")[1]
    data = await state.get_data()
    days = data.get("days", [])
    
    if time_mode == "single":
        # Одно время для всех дней
        await state.set_state(StartStates.waiting_any_time)
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
        first_day = sorted(days)[0]
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][first_day]
        msg = await query.message.edit_text(
            f"⏰ <b>Настройка времени для каждого дня</b>\n\n"
            f"📅 День <b>1 из {len(days)}</b>: <b>{day_name}</b>\n\n"
            "Укажите время тренировки:\n"
            "Формат: <code>HH:MM</code>\n"
            "Пример: <code>19:30</code>",
            reply_markup=None,
        )
        await state.update_data(any_day_times={}, any_current_day_index=0, any_last_bot_message_id=msg.message_id)
        await state.set_state(StartStates.waiting_any_day_time)
        await query.answer()
    else:
        await query.answer("❌ Неверный выбор", show_alert=True)


@router.message(StartStates.waiting_any_time)
async def start_any_time(message: Message, state: FSMContext, db: Database, scheduler, tz: ZoneInfo, config: Config) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    days = data.get("days", [])
    if user_id is None:
        await state.clear()
        await message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /start для начала регистрации."
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

    await state.update_data(any_time_mode="single")
    await queries.update_week_parity_offset(db, int(user_id), 0)
    schedules = [
        ScheduleCreate(user_id=int(user_id), weekday=day, time=time_str, week_type="any")
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
    formatted = format_schedule(schedule)
    profile_text = await build_profile_text(
        db, int(user_id), tz, config=config, tg_id=message.from_user.id
    )
    await message.answer(
        f"✅ <b>Регистрация завершена!</b>\n\n{profile_text}",
        reply_markup=main_menu_kb(config.admin_ids, message.from_user.id).as_markup(),
    )


@router.message(StartStates.waiting_any_day_time)
async def start_any_day_time(message: Message, state: FSMContext, db: Database, scheduler, tz: ZoneInfo, config: Config) -> None:
    if message.from_user is None or message.text is None:
        return
    data = await state.get_data()
    user_id = data.get("user_id")
    days = sorted(data.get("days", []))
    any_day_times = data.get("any_day_times", {})
    current_day_index = data.get("any_current_day_index", 0)
    
    if user_id is None or not days:
        await state.clear()
        await message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /start для начала регистрации."
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
    any_day_times[current_day] = time_str
    await state.update_data(any_day_times=any_day_times)
    
    # Переходим к следующему дню
    next_index = current_day_index + 1
    if next_index < len(days):
        await state.update_data(any_current_day_index=next_index)
        next_day = days[next_index]
        day_name = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][next_day]
        last_bot_message_id = data.get("any_last_bot_message_id")
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
                await state.update_data(any_last_bot_message_id=msg.message_id)
        else:
            msg = await message.answer(text)
            await state.update_data(any_last_bot_message_id=msg.message_id)
        return
    
    # Все дни настроены, сохраняем расписание
    await state.update_data(any_time_mode="multiple")
    
    # Удаляем последнее сообщение бота, если есть
    last_bot_message_id = data.get("any_last_bot_message_id")
    if last_bot_message_id:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=last_bot_message_id)
        except Exception:
            pass
    
    await queries.update_week_parity_offset(db, int(user_id), 0)
    schedules = [
        ScheduleCreate(user_id=int(user_id), weekday=day, time=any_day_times[day], week_type="any")
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
    profile_text = await build_profile_text(
        db, int(user_id), tz, config=config, tg_id=message.from_user.id
    )
    await message.answer(
        f"✅ <b>Регистрация завершена!</b>\n\n{profile_text}",
        reply_markup=main_menu_kb(config.admin_ids, message.from_user.id).as_markup(),
    )


@router.callback_query(StartStates.waiting_week_parity, F.data.startswith("weekparity:"))
async def start_week_parity(
    query,
    state: FSMContext,
    db: Database,
    scheduler,
    tz: ZoneInfo,
    config: Config,
) -> None:
    if query.data is None or query.message is None or query.from_user is None:
        return
    week_parity = query.data.split(":")[1]
    if week_parity not in {"even", "odd"}:
        await query.answer("❌ Неверный выбор", show_alert=True)
        return

    data = await state.get_data()
    user_id = data.get("user_id")
    setup_type = data.get("setup_type")
    
    if user_id is None:
        await state.clear()
        await query.message.answer(
            "⚠️ Сессия сброшена.\n\n"
            "Пожалуйста, нажмите /start для начала регистрации."
        )
        return

    is_even_week = week_parity == "even"
    offset = compute_week_parity_offset(datetime.now(tz), is_even_week)
    await queries.update_week_parity_offset(db, int(user_id), offset)

    if setup_type == "separate":
        # Сохраняем расписание для четных и нечетных недель
        even_days = data.get("even_days", [])
        even_time_mode = data.get("even_time_mode", "single")
        even_time = data.get("even_time")
        even_day_times = data.get("even_day_times", {})
        odd_days = data.get("odd_days", [])
        odd_time_mode = data.get("odd_time_mode", "single")
        odd_time = data.get("odd_time")
        odd_day_times = data.get("odd_day_times", {})
        
        schedules = []
        if even_days:
            if even_time_mode == "single" and even_time:
                for day in even_days:
                    schedules.append(ScheduleCreate(user_id=int(user_id), weekday=day, time=even_time, week_type="even"))
            elif even_time_mode == "multiple":
                for day in even_days:
                    if day in even_day_times:
                        schedules.append(ScheduleCreate(user_id=int(user_id), weekday=day, time=even_day_times[day], week_type="even"))
        if odd_days:
            if odd_time_mode == "single" and odd_time:
                for day in odd_days:
                    schedules.append(ScheduleCreate(user_id=int(user_id), weekday=day, time=odd_time, week_type="odd"))
            elif odd_time_mode == "multiple":
                for day in odd_days:
                    if day in odd_day_times:
                        schedules.append(ScheduleCreate(user_id=int(user_id), weekday=day, time=odd_day_times[day], week_type="odd"))
        
        for entry in schedules:
            await queries.add_workout_schedule(db, entry)
    else:
        # Не должно быть здесь для "any", но на всякий случай
        pass

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
    
    # Показываем итоговое расписание
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
    
    await query.message.edit_reply_markup(reply_markup=None)
    profile_text = await build_profile_text(
        db, int(user_id), tz, config=config, tg_id=query.from_user.id
    )
    await query.message.answer(
        f"✅ <b>Регистрация завершена!</b>\n\n{profile_text}",
        reply_markup=main_menu_kb(config.admin_ids, query.from_user.id).as_markup(),
    )
    await query.answer()
