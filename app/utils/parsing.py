from __future__ import annotations

from typing import Iterable

from pydantic import ValidationError

from app.db.models import WeekdaysInput


WEEKDAY_MAP = {
    "пн": 0,
    "пон": 0,
    "понедельник": 0,
    "вт": 1,
    "вто": 1,
    "вторник": 1,
    "ср": 2,
    "сре": 2,
    "среда": 2,
    "чт": 3,
    "чет": 3,
    "четверг": 3,
    "пт": 4,
    "пят": 4,
    "пятница": 4,
    "сб": 5,
    "суб": 5,
    "суббота": 5,
    "вс": 6,
    "вос": 6,
    "воскресенье": 6,
}


def parse_weekdays(value: str) -> list[int]:
    if not value:
        raise ValueError("weekday input is empty")
    tokens = [token.strip().lower() for token in value.replace(",", " ").split()]
    days = []
    for token in tokens:
        if token in WEEKDAY_MAP:
            days.append(WEEKDAY_MAP[token])
    try:
        parsed = WeekdaysInput(days=days)
    except ValidationError as exc:
        raise ValueError("invalid weekdays") from exc
    return parsed.days


def parse_time(value: str) -> str:
    if not value:
        raise ValueError("time is empty")
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("invalid time")
    hour_str, minute_str = parts
    if not (hour_str.isdigit() and minute_str.isdigit()):
        raise ValueError("invalid time")
    hour = int(hour_str)
    minute = int(minute_str)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("invalid time")
    return f"{hour:02d}:{minute:02d}"


def parse_weight(value: str) -> float:
    if not value:
        raise ValueError("weight is empty")
    normalized = value.strip().replace(",", ".")
    weight = float(normalized)
    if weight <= 0:
        raise ValueError("weight must be positive")
    return weight


def format_schedule(schedule: Iterable[dict], include_week_type: bool = False) -> str:
    """
    Форматирует расписание для отображения.
    
    Args:
        schedule: Список записей расписания
        include_week_type: Если True, добавляет метки (четные)/(нечетные) к каждому дню.
                          Если False (по умолчанию), метки не добавляются (для использования в секциях)
    """
    mapping = {
        0: "Пн",
        1: "Вт",
        2: "Ср",
        3: "Чт",
        4: "Пт",
        5: "Сб",
        6: "Вс",
    }
    
    # Группируем по дню и времени
    grouped: dict[tuple[int, str], set[str]] = {}
    for item in schedule:
        weekday = int(item['weekday'])
        time_str = item['time']
        week_type = item.get('week_type', 'any')
        key = (weekday, time_str)
        if key not in grouped:
            grouped[key] = set()
        grouped[key].add(week_type)
    
    # Формируем строки
    items = []
    for (weekday, time_str), week_types in sorted(grouped.items()):
        day_label = mapping[weekday]
        
        if include_week_type:
            # Обрабатываем типы недель (старый формат с метками)
            if 'any' in week_types or len(week_types) == 0:
                items.append(f"{day_label} {time_str}")
            elif len(week_types) == 1:
                wt = list(week_types)[0]
                if wt == 'even':
                    items.append(f"{day_label} {time_str} (четные)")
                elif wt == 'odd':
                    items.append(f"{day_label} {time_str} (нечетные)")
                else:
                    items.append(f"{day_label} {time_str}")
            else:
                week_labels = []
                if 'even' in week_types:
                    week_labels.append('четные')
                if 'odd' in week_types:
                    week_labels.append('нечетные')
                if week_labels:
                    items.append(f"{day_label} {time_str} ({', '.join(week_labels)})")
                else:
                    items.append(f"{day_label} {time_str}")
        else:
            # Простой формат без меток недель (для использования в секциях)
            items.append(f"{day_label} {time_str}")
    
    return ", ".join(items) if items else "нет"


def format_days(days: Iterable[int]) -> str:
    mapping = {
        0: "Пн",
        1: "Вт",
        2: "Ср",
        3: "Чт",
        4: "Пт",
        5: "Сб",
        6: "Вс",
    }
    ordered = [mapping[day] for day in sorted(set(days)) if day in mapping]
    return " ".join(ordered) if ordered else "нет"
