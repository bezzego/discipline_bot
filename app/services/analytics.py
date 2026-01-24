from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import calendar

from app.db.database import Database
from app.db import queries
from app.services.discipline import calculate_discipline_score, count_scheduled_workouts


@dataclass(frozen=True)
class MonthlyReport:
    start_weight: Optional[float]
    end_weight: Optional[float]
    diff: Optional[float]
    diff_percent: Optional[float]
    completed: int
    missed: int
    discipline_score: float
    weights: list[tuple[datetime, float]]


def month_range(target: datetime) -> tuple[datetime, datetime]:
    start = datetime(target.year, target.month, 1, tzinfo=target.tzinfo)
    last_day = calendar.monthrange(target.year, target.month)[1]
    end = datetime(target.year, target.month, last_day, 23, 59, 59, tzinfo=target.tzinfo)
    return start, end


def previous_month_range(target: datetime) -> tuple[datetime, datetime]:
    first_this_month = datetime(target.year, target.month, 1, tzinfo=target.tzinfo)
    prev_month_last = first_this_month - timedelta(seconds=1)
    return month_range(prev_month_last)


async def build_monthly_report(
    db: Database,
    user_id: int,
    start: datetime,
    end: datetime,
    week_parity_offset: int,
) -> MonthlyReport:
    schedule = await queries.get_workout_schedule(db, user_id)
    stats = await queries.get_workout_stats(db, user_id, start, end)
    scheduled = count_scheduled_workouts(schedule, start, end, week_parity_offset)
    score = calculate_discipline_score(stats["done"], scheduled)

    first_weight = await queries.get_first_weight_between(db, user_id, start, end)
    last_weight = await queries.get_last_weight_between(db, user_id, start, end)

    start_weight = first_weight["weight"] if first_weight else None
    end_weight = last_weight["weight"] if last_weight else None

    diff = None
    diff_percent = None
    if start_weight is not None and end_weight is not None:
        diff = round(end_weight - start_weight, 2)
        if start_weight != 0:
            diff_percent = round((diff / start_weight) * 100, 2)

    weights = await queries.get_weights_between(db, user_id, start, end)
    weight_points = [(datetime.fromisoformat(w["date"]), float(w["weight"])) for w in weights]

    return MonthlyReport(
        start_weight=start_weight,
        end_weight=end_weight,
        diff=diff,
        diff_percent=diff_percent,
        completed=stats["done"],
        missed=stats["missed"],
        discipline_score=score,
        weights=weight_points,
    )
