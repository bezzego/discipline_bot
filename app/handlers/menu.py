from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from zoneinfo import ZoneInfo

from app.config import Config
from app.db.database import Database
from app.db import queries
from app.handlers import schedule, reports, profile
from app.handlers.weight import WeightStates
from app.handlers.calories import CalorieStates
from app.services.access import (
    PRODUCT_DESCRIPTION,
    PRODUCT_PRICE,
    access_status_display,
)
from app.utils.keyboards import main_menu_kb, schedule_mode_kb, subscription_kb
from app.utils.parsing import format_schedule


router = Router()


@router.callback_query(F.data.startswith("menu:"))
async def menu_handler(
    query: CallbackQuery,
    state: FSMContext,
    db: Database,
    tz: ZoneInfo,
    config: Config,
) -> None:
    if query.data is None or query.message is None or query.from_user is None:
        return
    action = query.data.split(":")[1]
    await query.answer()

    if action == "schedule":
        # Проверяем, что пользователь существует
        user = await queries.get_user_by_tg_id(db, query.from_user.id)
        if not user:
            await query.message.answer(
                "👋 Привет!\n\n"
                "Для начала работы выполните команду /start"
            )
            return
        
        # Вызываем schedule_command напрямую с правильными параметрами
        if query.message is None:
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
        await state.set_state(schedule.ScheduleStates.waiting_mode)
        await query.message.answer(
            f"📋 <b>Управление расписанием</b>\n\n"
            f"{schedule_text}\n\n"
            f"<b>Выберите действие:</b>",
            reply_markup=schedule_mode_kb().as_markup(),
        )
        return

    if action == "weight":
        await state.set_state(WeightStates.waiting_weight)
        await query.message.answer(
            "⚖️ <b>Введите текущий вес</b>\n\n"
            "Укажите вес в килограммах одним числом.\n\n"
            "Примеры:\n"
            "• <code>82.4</code>\n"
            "• <code>75</code>\n"
            "• <code>90.5</code>"
        )
        return

    if action == "calories":
        user = await queries.get_user_by_tg_id(db, query.from_user.id)
        if not user:
            await query.message.answer("👋 Для начала работы выполните /start")
            return
        await state.set_state(CalorieStates.waiting_calories)
        await state.update_data(user_id=int(user["id"]))
        await query.message.answer(
            "🔥 <b>Добавить калории</b>\n\n"
            "Введите количество ккал (целое число).\n\n"
            "Примеры: <code>500</code>, <code>1200</code>"
        )
        return

    if action == "report":
        # Проверяем, что пользователь существует
        user = await queries.get_user_by_tg_id(db, query.from_user.id)
        if not user:
            if query.message:
                await query.message.answer(
                "👋 Привет!\n\n"
                "Для начала работы выполните команду /start"
            )
            return
        if query.message is None:
            return
        week_parity_offset = int(user.get("week_parity_offset") or 0)
        await reports.show_report(query.message, db, tz, int(user["id"]), week_parity_offset)
        return

    if action == "stats":
        # Проверяем, что пользователь существует
        user = await queries.get_user_by_tg_id(db, query.from_user.id)
        if not user:
            if query.message:
                await query.message.answer(
                "👋 Привет!\n\n"
                "Для начала работы выполните команду /start"
            )
            return
        if query.message is None:
            return
        week_parity_offset = int(user.get("week_parity_offset") or 0)
        await reports.show_stats(query.message, db, tz, int(user["id"]), week_parity_offset)
        return

    if action == "profile":
        user = await queries.get_user_by_tg_id(db, query.from_user.id)
        if not user:
            if query.message:
                await query.message.answer(
                    "👋 Привет!\n\n"
                    "Для начала работы выполните команду /start"
                )
            return
        if query.message is None:
            return
        await profile.show_profile(query.message, db, tz, int(user["id"]), config)
        return

    if action == "subscription":
        user = await queries.get_user_by_tg_id(db, query.from_user.id)
        if not user:
            if query.message:
                await query.message.answer("👋 Для начала работы выполните /start")
            return
        if query.message is None:
            return
        status_text, pay_now, extend = access_status_display(
            user, query.from_user.id, config, tz
        )
        text = (
            "📋 <b>Подписка</b>\n\n"
            f"🔐 <b>Доступ:</b> {status_text}\n\n"
            f"{PRODUCT_DESCRIPTION}\n\n"
            f"{PRODUCT_PRICE}\n\n"
            "Подробнее — /tariff"
        )
        kb = subscription_kb(pay_now=pay_now, extend=extend)
        if pay_now or extend:
            await query.message.answer(text, reply_markup=kb.as_markup())
        else:
            await query.message.answer(
                text,
                reply_markup=main_menu_kb(config.admin_ids, query.from_user.id).as_markup(),
            )
        return

    if action == "back":
        await query.message.answer(
            "Главное меню:",
            reply_markup=main_menu_kb(config.admin_ids, query.from_user.id).as_markup(),
        )
        return

    if action == "admin":
        from app.handlers.admin import admin_panel_handler
        await admin_panel_handler(query, config)
        return
