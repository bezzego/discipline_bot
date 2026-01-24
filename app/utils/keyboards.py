from __future__ import annotations

from typing import Optional
from aiogram.utils.keyboard import InlineKeyboardBuilder


def workout_confirmation_kb(workout_at: str) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Выполнено", callback_data=f"workout:done:{workout_at}")
    builder.button(text="Пропущено", callback_data=f"workout:missed:{workout_at}")
    builder.adjust(2)
    return builder


def log_status_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Выполнено", callback_data="logstatus:done")
    builder.button(text="Пропущено", callback_data="logstatus:missed")
    builder.adjust(2)
    return builder


def main_menu_kb(admin_ids: Optional[list[int]] = None, user_id: Optional[int] = None) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Профиль", callback_data="menu:profile")
    builder.button(text="Расписание", callback_data="menu:schedule")
    builder.button(text="Вес", callback_data="menu:weight")
    builder.button(text="Калории", callback_data="menu:calories")
    builder.button(text="Отчет", callback_data="menu:report")
    builder.button(text="Статистика", callback_data="menu:stats")
    
    # Добавляем кнопку админа только для админов
    if admin_ids and user_id and user_id in admin_ids:
        builder.button(text="🔐 Админ-панель", callback_data="menu:admin")
        builder.adjust(2, 2, 1, 1, 1)
    else:
        builder.adjust(2, 2, 2, 1)
    
    return builder


def weekdays_kb(selected: list[int]) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    labels = {
        0: "Пн",
        1: "Вт",
        2: "Ср",
        3: "Чт",
        4: "Пт",
        5: "Сб",
        6: "Вс",
    }
    selected_set = set(selected)
    for day in range(7):
        label = labels[day]
        if day in selected_set:
            label = f"{label} ✓"
        builder.button(text=label, callback_data=f"days:toggle:{day}")
    builder.button(text="Готово", callback_data="days:done")
    builder.button(text="Сброс", callback_data="days:reset")
    builder.adjust(3, 3, 3)
    return builder


def week_type_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Каждая неделя", callback_data="weektype:any")
    builder.button(text="Только четные недели", callback_data="weektype:even")
    builder.button(text="Только нечетные недели", callback_data="weektype:odd")
    builder.button(text="Четные и нечетные (оба варианта)", callback_data="weektype:both")
    builder.adjust(1, 1, 1, 1)
    return builder


def week_parity_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Эта неделя четная", callback_data="weekparity:even")
    builder.button(text="Эта неделя нечетная", callback_data="weekparity:odd")
    builder.adjust(1, 1)
    return builder


def schedule_mode_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Редактировать четные недели", callback_data="schedulemode:even")
    builder.button(text="✏️ Редактировать нечетные недели", callback_data="schedulemode:odd")
    builder.button(text="✏️ Редактировать все недели", callback_data="schedulemode:any")
    builder.button(text="👁️ Просмотреть расписание", callback_data="schedulemode:view")
    builder.adjust(1, 1, 1, 1)
    return builder


def time_mode_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="Одно время для всех дней", callback_data="timemode:single")
    builder.button(text="Разное время для каждого дня", callback_data="timemode:multiple")
    builder.adjust(1, 1)
    return builder


def gender_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.button(text="Мужской", callback_data="gender:m")
    b.button(text="Женский", callback_data="gender:f")
    b.adjust(2)
    return b


def activity_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.button(text="Почти нет движения", callback_data="activity:sedentary")
    b.button(text="1–3 дня лёгкая активность", callback_data="activity:light")
    b.button(text="3–5 дней умеренная", callback_data="activity:moderate")
    b.button(text="6–7 дней активность", callback_data="activity:active")
    b.button(text="Тяжёлые тренировки / работа", callback_data="activity:very_active")
    b.adjust(1, 1, 1, 1, 1)
    return b


def goal_kb() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.button(text="Похудение", callback_data="goal:lose")
    b.button(text="Удержание веса", callback_data="goal:maintain")
    b.button(text="Набор массы", callback_data="goal:gain")
    b.adjust(1, 1, 1)
    return b


def admin_panel_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика бота", callback_data="admin:stats")
    builder.button(text="📥 Выгрузить в Excel", callback_data="admin:export")
    builder.button(text="👥 Список пользователей", callback_data="admin:users")
    builder.button(text="📢 Рассылка", callback_data="admin:broadcast")
    builder.button(text="🔙 Назад", callback_data="admin:back")
    builder.adjust(1, 1, 1, 1, 1)
    return builder
