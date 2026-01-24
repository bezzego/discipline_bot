"""
Проверка доступа: триал 5 дней, подписка 299₽/мес, админы всегда бесплатно.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Config
from app.db.database import Database

TRIAL_DAYS = 5
SUBSCRIPTION_MONTHS = 1
SUBSCRIPTION_PRICE_RUB = 299

# Описание и стоимость товаров/услуг (обязательно для размещения)
PRODUCT_DESCRIPTION = (
    "<b>Описание услуги:</b> Подписка на Discipline Bot — ежемесячный доступ к функционалу бота. "
    "Включено: отслеживание тренировок, веса и калорий; расчёт нормы калорий и ИМТ по формуле Mifflin–St Jeor; "
    "расписание тренировок; отчёты и статистика; напоминания о тренировках и взвешивании."
)
PRODUCT_PRICE = f"<b>Стоимость:</b> {SUBSCRIPTION_PRICE_RUB} ₽ (российских рублей) в месяц."


def is_admin(tg_id: int, config: Config) -> bool:
    return config.admin_ids and tg_id in config.admin_ids


async def has_access(
    db: Database,
    tg_id: int,
    user: dict | None,
    config: Config,
    tz: ZoneInfo,
) -> bool:
    """
    Есть ли доступ: админ — всегда; иначе подписка активна или триал не истёк.
    user — строка из get_user_by_tg_id (или None, если не зарегистрирован).
    """
    if is_admin(tg_id, config):
        return True
    if not user:
        return False
    now = datetime.now(tz)
    today = now.date().isoformat()

    sub_ends = user.get("subscription_ends_at")
    if sub_ends:
        try:
            if str(sub_ends) >= today:
                return True
        except Exception:
            pass

    created = user.get("created_at")
    if not created:
        return False
    try:
        if isinstance(created, str) and "T" in created:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        else:
            created_dt = datetime.fromisoformat(str(created))
    except Exception:
        return False
    if created_dt.tzinfo is None:
        created_dt = created_dt.replace(tzinfo=tz)
    trial_end = (created_dt + timedelta(days=TRIAL_DAYS)).date()
    return now.date() <= trial_end


def subscription_end_after_months(now: datetime, months: int = SUBSCRIPTION_MONTHS) -> str:
    """Дата окончания подписки через N месяцев (YYYY-MM-DD). Упрощённо: +30 дней за месяц."""
    end = (now.date() + timedelta(days=30 * months)).isoformat()
    return end
