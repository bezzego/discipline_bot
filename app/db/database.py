from __future__ import annotations

import aiosqlite
from typing import Any, Iterable, Optional


class Database:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON;")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is None:
            return
        await self._conn.close()
        self._conn = None

    async def execute(self, query: str, params: Iterable[Any] | None = None) -> None:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        await self._conn.execute(query, params or [])
        await self._conn.commit()

    async def execute_many(self, query: str, params: Iterable[Iterable[Any]]) -> None:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        await self._conn.executemany(query, params)
        await self._conn.commit()

    async def fetch_one(self, query: str, params: Iterable[Any] | None = None) -> Optional[aiosqlite.Row]:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        async with self._conn.execute(query, params or []) as cursor:
            return await cursor.fetchone()

    async def fetch_all(self, query: str, params: Iterable[Any] | None = None) -> list[aiosqlite.Row]:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        async with self._conn.execute(query, params or []) as cursor:
            rows = await cursor.fetchall()
        return list(rows)


async def _column_exists(db: Database, table: str, column: str) -> bool:
    rows = await db.fetch_all(f"PRAGMA table_info({table});")
    return any(row["name"] == column for row in rows)


async def init_db(db: Database) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER NOT NULL UNIQUE,
            target_weight REAL,
            week_parity_offset INTEGER,
            created_at TEXT NOT NULL
        );
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS workout_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            weekday INTEGER NOT NULL,
            time TEXT NOT NULL,
            week_type TEXT NOT NULL DEFAULT 'any',
            UNIQUE(user_id, weekday, time, week_type),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS workout_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL,
            duration INTEGER,
            notes TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            weight REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_workout_logs_user_date ON workout_logs(user_id, date);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_weights_user_date ON weights(user_id, date);")

    if not await _column_exists(db, "users", "week_parity_offset"):
        await db.execute("ALTER TABLE users ADD COLUMN week_parity_offset INTEGER;")

    if not await _column_exists(db, "workout_schedule", "week_type"):
        await db.execute(
            """
            CREATE TABLE workout_schedule_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                weekday INTEGER NOT NULL,
                time TEXT NOT NULL,
                week_type TEXT NOT NULL DEFAULT 'any',
                UNIQUE(user_id, weekday, time, week_type),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )
        await db.execute(
            """
            INSERT INTO workout_schedule_new (id, user_id, weekday, time, week_type)
            SELECT id, user_id, weekday, time, 'any' FROM workout_schedule;
            """
        )
        await db.execute("DROP TABLE workout_schedule;")
        await db.execute("ALTER TABLE workout_schedule_new RENAME TO workout_schedule;")

    # Калории и антропометрия (норма калорий, ИМТ, цель)
    for col, dtype in [
        ("height_cm", "REAL"),
        ("birth_year", "INTEGER"),
        ("gender", "TEXT"),
        ("activity_level", "TEXT"),
        ("goal", "TEXT"),
    ]:
        if not await _column_exists(db, "users", col):
            await db.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype};")

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS calorie_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            calories INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_calorie_logs_user_date ON calorie_logs(user_id, date);")

    if not await _column_exists(db, "users", "subscription_ends_at"):
        await db.execute("ALTER TABLE users ADD COLUMN subscription_ends_at TEXT;")

    # Таблица платежей
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            payment_id TEXT NOT NULL UNIQUE,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'RUB',
            status TEXT NOT NULL,
            payment_method_id TEXT,
            created_at TEXT NOT NULL,
            paid_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_payment_id ON payments(payment_id);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);")

    # Таблица рекуррентных подписок
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS recurring_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            payment_method_id TEXT NOT NULL,
            amount REAL NOT NULL,
            currency TEXT NOT NULL DEFAULT 'RUB',
            next_payment_date TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_recurring_user_id ON recurring_subscriptions(user_id);")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_recurring_next_payment ON recurring_subscriptions(next_payment_date);")

    # Таблица настроек (глобальные настройки бота)
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    
    # Инициализируем цену подписки по умолчанию, если её нет
    existing_price = await db.fetch_one("SELECT value FROM settings WHERE key = 'subscription_price_rub';")
    if not existing_price:
        from datetime import datetime
        await db.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('subscription_price_rub', '299', ?);",
            (datetime.now().isoformat(),)
        )
