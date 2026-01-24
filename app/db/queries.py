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
