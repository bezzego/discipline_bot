from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from app.db.database import Database
from app.db.models import ScheduleCreate, WorkoutLogCreate, WeightEntry


async def create_user(db: Database, tg_id: int, created_at: datetime) -> int:
    await db.execute(
        "INSERT OR IGNORE INTO users (tg_id, target_weight, week_parity_offset, created_at) VALUES (?, ?, ?, ?);",
        (tg_id, None, None, created_at.isoformat()),
    )
    row = await db.fetch_one("SELECT id FROM users WHERE tg_id = ?;", (tg_id,))
    if row is None:
        raise RuntimeError("failed to create user")
    return int(row["id"])


async def get_user_by_tg_id(db: Database, tg_id: int) -> Optional[dict]:
    row = await db.fetch_one("SELECT * FROM users WHERE tg_id = ?;", (tg_id,))
    return dict(row) if row else None


async def update_target_weight(db: Database, user_id: int, target_weight: float) -> None:
    await db.execute("UPDATE users SET target_weight = ? WHERE id = ?;", (target_weight, user_id))


async def update_week_parity_offset(db: Database, user_id: int, offset: int) -> None:
    await db.execute("UPDATE users SET week_parity_offset = ? WHERE id = ?;", (offset, user_id))


async def list_users(db: Database) -> list[dict]:
    rows = await db.fetch_all("SELECT * FROM users;")
    return [dict(row) for row in rows]


async def replace_workout_schedule(db: Database, user_id: int, schedules: Iterable[ScheduleCreate]) -> None:
    await db.execute("DELETE FROM workout_schedule WHERE user_id = ?;", (user_id,))
    payload = [(s.user_id, s.weekday, s.time, s.week_type) for s in schedules]
    if payload:
        await db.execute_many(
            "INSERT OR IGNORE INTO workout_schedule (user_id, weekday, time, week_type) VALUES (?, ?, ?, ?);",
            payload,
        )


async def add_workout_schedule(db: Database, schedule: ScheduleCreate) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO workout_schedule (user_id, weekday, time, week_type) VALUES (?, ?, ?, ?);",
        (schedule.user_id, schedule.weekday, schedule.time, schedule.week_type),
    )


async def get_workout_schedule(db: Database, user_id: int) -> list[dict]:
    rows = await db.fetch_all(
        "SELECT weekday, time, week_type FROM workout_schedule WHERE user_id = ? ORDER BY weekday, time;",
        (user_id,),
    )
    return [dict(row) for row in rows]


async def add_weight_entry(db: Database, entry: WeightEntry) -> None:
    await db.execute(
        "INSERT INTO weights (user_id, date, weight) VALUES (?, ?, ?);",
        (entry.user_id, entry.date.isoformat(), entry.weight),
    )


async def get_latest_weight(db: Database, user_id: int) -> Optional[dict]:
    row = await db.fetch_one(
        "SELECT * FROM weights WHERE user_id = ? ORDER BY date DESC LIMIT 1;",
        (user_id,),
    )
    return dict(row) if row else None


async def get_weights_between(db: Database, user_id: int, start: datetime, end: datetime) -> list[dict]:
    rows = await db.fetch_all(
        "SELECT * FROM weights WHERE user_id = ? AND date >= ? AND date <= ? ORDER BY date ASC;",
        (user_id, start.isoformat(), end.isoformat()),
    )
    return [dict(row) for row in rows]


async def get_first_weight_between(db: Database, user_id: int, start: datetime, end: datetime) -> Optional[dict]:
    row = await db.fetch_one(
        "SELECT * FROM weights WHERE user_id = ? AND date >= ? AND date <= ? ORDER BY date ASC LIMIT 1;",
        (user_id, start.isoformat(), end.isoformat()),
    )
    return dict(row) if row else None


async def get_last_weight_between(db: Database, user_id: int, start: datetime, end: datetime) -> Optional[dict]:
    row = await db.fetch_one(
        "SELECT * FROM weights WHERE user_id = ? AND date >= ? AND date <= ? ORDER BY date DESC LIMIT 1;",
        (user_id, start.isoformat(), end.isoformat()),
    )
    return dict(row) if row else None


async def upsert_workout_log(db: Database, log: WorkoutLogCreate) -> None:
    existing = await db.fetch_one(
        "SELECT id FROM workout_logs WHERE user_id = ? AND date = ?;",
        (log.user_id, log.date.isoformat()),
    )
    if existing:
        await db.execute(
            "UPDATE workout_logs SET status = ?, duration = ?, notes = ? WHERE id = ?;",
            (log.status, log.duration, log.notes, int(existing["id"])),
        )
        return
    await db.execute(
        "INSERT INTO workout_logs (user_id, date, status, duration, notes) VALUES (?, ?, ?, ?, ?);",
        (log.user_id, log.date.isoformat(), log.status, log.duration, log.notes),
    )


async def workout_log_exists(db: Database, user_id: int, workout_at: datetime) -> bool:
    row = await db.fetch_one(
        "SELECT 1 FROM workout_logs WHERE user_id = ? AND date = ?;",
        (user_id, workout_at.isoformat()),
    )
    return row is not None


async def get_workout_stats(db: Database, user_id: int, start: datetime, end: datetime) -> dict:
    rows = await db.fetch_all(
        """
        SELECT status, COUNT(*) as cnt
        FROM workout_logs
        WHERE user_id = ? AND date >= ? AND date <= ?
        GROUP BY status;
        """,
        (user_id, start.isoformat(), end.isoformat()),
    )
    stats = {"done": 0, "missed": 0}
    for row in rows:
        status = row["status"]
        if status in stats:
            stats[status] = int(row["cnt"])
    return stats


async def get_workout_logs_between(db: Database, user_id: int, start: datetime, end: datetime) -> list[dict]:
    rows = await db.fetch_all(
        "SELECT * FROM workout_logs WHERE user_id = ? AND date >= ? AND date <= ? ORDER BY date ASC;",
        (user_id, start.isoformat(), end.isoformat()),
    )
    return [dict(row) for row in rows]


async def update_user_calorie_params(
    db: Database,
    user_id: int,
    *,
    height_cm: float | None = None,
    birth_year: int | None = None,
    gender: str | None = None,
    activity_level: str | None = None,
    goal: str | None = None,
    target_weight: float | None = None,
) -> None:
    """Обновляет параметры для расчёта калорий и цели."""
    updates, params = [], []
    if height_cm is not None:
        updates.append("height_cm = ?")
        params.append(height_cm)
    if birth_year is not None:
        updates.append("birth_year = ?")
        params.append(birth_year)
    if gender is not None:
        updates.append("gender = ?")
        params.append(gender)
    if activity_level is not None:
        updates.append("activity_level = ?")
        params.append(activity_level)
    if goal is not None:
        updates.append("goal = ?")
        params.append(goal)
    if target_weight is not None:
        updates.append("target_weight = ?")
        params.append(target_weight)
    if not updates:
        return
    params.append(user_id)
    await db.execute(
        f"UPDATE users SET {', '.join(updates)} WHERE id = ?;",
        params,
    )


async def add_calorie_log(
    db: Database,
    user_id: int,
    date_day: str,
    calories: int,
    created_at: datetime,
) -> None:
    """Добавляет запись о калориях за день (можно несколько записей в день — суммируем)."""
    await db.execute(
        "INSERT INTO calorie_logs (user_id, date, calories, created_at) VALUES (?, ?, ?, ?);",
        (user_id, date_day, calories, created_at.isoformat()),
    )


async def get_calories_sum_for_day(db: Database, user_id: int, date_day: str) -> int:
    """Сумма калорий за день."""
    row = await db.fetch_one(
        "SELECT COALESCE(SUM(calories), 0) AS total FROM calorie_logs WHERE user_id = ? AND date = ?;",
        (user_id, date_day),
    )
    return int(row["total"]) if row else 0


async def get_user_by_id(db: Database, user_id: int) -> Optional[dict]:
    """Пользователь по id."""
    row = await db.fetch_one("SELECT * FROM users WHERE id = ?;", (user_id,))
    return dict(row) if row else None


async def set_subscription_ends_at(db: Database, user_id: int, date_iso: str) -> None:
    """Установить дату окончания подписки (YYYY-MM-DD)."""
    await db.execute("UPDATE users SET subscription_ends_at = ? WHERE id = ?;", (date_iso, user_id))


async def create_payment(
    db: Database,
    user_id: int,
    payment_id: str,
    amount: float,
    currency: str,
    status: str,
    payment_method_id: str | None,
    created_at: datetime,
    paid_at: datetime | None = None,
) -> None:
    """Создать запись о платеже."""
    await db.execute(
        """
        INSERT INTO payments (user_id, payment_id, amount, currency, status, payment_method_id, created_at, paid_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            user_id,
            payment_id,
            amount,
            currency,
            status,
            payment_method_id,
            created_at.isoformat(),
            paid_at.isoformat() if paid_at else None,
        ),
    )


async def update_payment_status(
    db: Database,
    payment_id: str,
    status: str,
    paid_at: datetime | None = None,
) -> None:
    """Обновить статус платежа."""
    await db.execute(
        "UPDATE payments SET status = ?, paid_at = ? WHERE payment_id = ?;",
        (status, paid_at.isoformat() if paid_at else None, payment_id),
    )


async def get_payment_by_id(db: Database, payment_id: str) -> Optional[dict]:
    """Получить платеж по payment_id."""
    row = await db.fetch_one("SELECT * FROM payments WHERE payment_id = ?;", (payment_id,))
    return dict(row) if row else None


async def get_pending_payments(db: Database) -> list[dict]:
    """Получить все платежи со статусом pending или waiting_for_capture."""
    rows = await db.fetch_all(
        "SELECT * FROM payments WHERE status IN ('pending', 'waiting_for_capture');"
    )
    return [dict(row) for row in rows]




async def create_recurring_subscription(
    db: Database,
    user_id: int,
    payment_method_id: str,
    amount: float,
    currency: str,
    next_payment_date: str,
    created_at: datetime,
) -> None:
    """Создать рекуррентную подписку."""
    await db.execute(
        """
        INSERT OR REPLACE INTO recurring_subscriptions 
        (user_id, payment_method_id, amount, currency, next_payment_date, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?);
        """,
        (
            user_id,
            payment_method_id,
            amount,
            currency,
            next_payment_date,
            created_at.isoformat(),
        ),
    )


async def get_recurring_subscription(db: Database, user_id: int) -> Optional[dict]:
    """Получить активную рекуррентную подписку пользователя."""
    row = await db.fetch_one(
        "SELECT * FROM recurring_subscriptions WHERE user_id = ? AND is_active = 1;",
        (user_id,),
    )
    return dict(row) if row else None


async def update_recurring_subscription_next_payment(
    db: Database,
    user_id: int,
    next_payment_date: str,
) -> None:
    """Обновить дату следующего платежа."""
    await db.execute(
        "UPDATE recurring_subscriptions SET next_payment_date = ? WHERE user_id = ? AND is_active = 1;",
        (next_payment_date, user_id),
    )


async def deactivate_recurring_subscription(db: Database, user_id: int) -> None:
    """Деактивировать рекуррентную подписку."""
    await db.execute(
        "UPDATE recurring_subscriptions SET is_active = 0 WHERE user_id = ?;",
        (user_id,),
    )


async def get_recurring_subscriptions_due(db: Database, date_iso: str) -> list[dict]:
    """Получить рекуррентные подписки, у которых наступила дата следующего платежа."""
    rows = await db.fetch_all(
        "SELECT * FROM recurring_subscriptions WHERE is_active = 1 AND next_payment_date <= ?;",
        (date_iso,),
    )
    return [dict(row) for row in rows]


async def get_setting(db: Database, key: str) -> Optional[str]:
    """Получить значение настройки по ключу."""
    row = await db.fetch_one("SELECT value FROM settings WHERE key = ?;", (key,))
    return row["value"] if row else None


async def set_setting(db: Database, key: str, value: str, updated_at: datetime) -> None:
    """Установить значение настройки."""
    await db.execute(
        "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?);",
        (key, value, updated_at.isoformat()),
    )


async def get_subscription_price(db: Database) -> float:
    """Получить цену подписки из настроек (по умолчанию 299)."""
    price_str = await get_setting(db, "subscription_price_rub")
    if price_str:
        try:
            return float(price_str)
        except (ValueError, TypeError):
            pass
    return 299.0  # Значение по умолчанию


async def set_subscription_price(db: Database, price: float, updated_at: datetime) -> None:
    """Установить цену подписки."""
    await set_setting(db, "subscription_price_rub", str(price), updated_at)
