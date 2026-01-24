from __future__ import annotations

from datetime import datetime, timedelta


def calculate_discipline_score(completed: int, scheduled: int) -> float:
    if scheduled <= 0:
        return 0.0
    return round((completed / scheduled) * 100, 2)

def compute_week_parity_offset(reference: datetime, is_even_week: bool) -> int:
    iso_even = reference.isocalendar().week % 2 == 0
    return 0 if iso_even == is_even_week else 1


def is_week_allowed(target: datetime, offset: int, week_type: str) -> bool:
    normalized = week_type.lower().strip()
    if normalized == "any":
        return True
    iso_even = target.isocalendar().week % 2 == 0
    parity = 0 if iso_even else 1
    user_even = (parity + offset) % 2 == 0
    if normalized == "even":
        return user_even
    if normalized == "odd":
        return not user_even
    return True


def is_user_week_even(target: datetime, offset: int) -> bool:
    iso_even = target.isocalendar().week % 2 == 0
    parity = 0 if iso_even else 1
    return (parity + offset) % 2 == 0


def count_scheduled_workouts(
    schedule: list[dict],
    start: datetime,
    end: datetime,
    week_parity_offset: int,
) -> int:
    if start > end:
        return 0

    schedule_by_weekday: dict[int, list[str]] = {}
    for entry in schedule:
        weekday = int(entry["weekday"])
        schedule_by_weekday.setdefault(weekday, []).append(entry.get("week_type", "any"))

    current = start.date()
    end_date = end.date()
    total = 0
    while current <= end_date:
        week_types = schedule_by_weekday.get(current.weekday(), [])
        if week_types:
            target_dt = datetime.combine(current, datetime.min.time(), tzinfo=start.tzinfo)
            for week_type in week_types:
                if is_week_allowed(target_dt, week_parity_offset, week_type):
                    total += 1
        current += timedelta(days=1)
    return total
