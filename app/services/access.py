"""
Проверка доступа: триал 5 дней, подписка (цена настраивается), админы всегда бесплатно.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Config
from app.db.database import Database
from app.db import queries

TRIAL_DAYS = 5
SUBSCRIPTION_MONTHS = 1
# Значение по умолчанию (используется только если БД недоступна)
DEFAULT_SUBSCRIPTION_PRICE_RUB = 299.0

# Описание и стоимость товаров/услуг (обязательно для размещения)
PRODUCT_DESCRIPTION = (
    "<b>Описание услуги:</b> Подписка на Discipline Bot — ежемесячный доступ к функционалу бота. "
    "Включено: отслеживание тренировок, веса и калорий; расчёт нормы калорий и ИМТ по формуле Mifflin–St Jeor; "
    "расписание тренировок; отчёты и статистика; напоминания о тренировках и взвешивании."
)


async def get_subscription_price_rub(db: Database) -> float:
    """Получить цену подписки из БД."""
    try:
        return await queries.get_subscription_price(db)
    except Exception:
        return DEFAULT_SUBSCRIPTION_PRICE_RUB


async def get_product_price_text(db: Database) -> str:
    """Получить текст с ценой подписки."""
    price = await get_subscription_price_rub(db)
    return f"<b>Стоимость:</b> {price:.0f} ₽ (российских рублей) в месяц."


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


def _parse_created_at(created, tz: ZoneInfo) -> datetime | None:
    if not created:
        return None
    try:
        if isinstance(created, str) and "T" in created:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        else:
            created_dt = datetime.fromisoformat(str(created))
    except Exception:
        return None
    if created_dt.tzinfo is None:
        created_dt = created_dt.replace(tzinfo=tz)
    return created_dt


def trial_days_left(user: dict | None, tz: ZoneInfo) -> int:
    """Сколько дней осталось до конца пробного периода. 0 если триал истёк или есть подписка."""
    if not user:
        return 0
    sub_ends = user.get("subscription_ends_at")
    if sub_ends:
        try:
            from datetime import date
            if str(sub_ends) >= date.today().isoformat():
                return 0  # подписка активна, триал не считается
        except Exception:
            pass
    created_dt = _parse_created_at(user.get("created_at"), tz)
    if not created_dt:
        return 0
    now = datetime.now(tz)
    trial_end = (created_dt + timedelta(days=TRIAL_DAYS)).date()
    if now.date() > trial_end:
        return 0
    delta = (trial_end - now.date()).days
    return max(0, delta)


def format_sub_end_display(date_iso: str) -> str:
    """YYYY-MM-DD → DD.MM.YYYY для отображения."""
    if not date_iso:
        return ""
    try:
        parts = str(date_iso).strip()[:10].split("-")
        if len(parts) == 3:
            return f"{parts[2]}.{parts[1]}.{parts[0]}"
    except Exception:
        pass
    return str(date_iso)


def access_status_display(user: dict | None, tg_id: int, config: Config, tz: ZoneInfo) -> tuple[str, bool, bool]:
    """
    Текст статуса доступа и флаги для кнопок.
    Возвращает (текст, показать_оплатить_сейчас, показать_продлить).
    """
    if not user:
        return "Нет доступа. Выполните /start.", False, False
    if is_admin(tg_id, config):
        return "Доступ: без ограничений (админ).", False, False

    now = datetime.now(tz)
    today = now.date().isoformat()
    sub_ends = user.get("subscription_ends_at")

    if sub_ends and str(sub_ends) >= today:
        end_str = format_sub_end_display(str(sub_ends))
        return f"Подписка до <b>{end_str}</b>.", False, True

    days = trial_days_left(user, tz)
    if days > 0:
        if days == 1:
            d = "1 день"
        elif 2 <= days <= 4:
            d = f"{days} дня"
        else:
            d = f"{days} дней"
        return f"Пробный период: осталось <b>{d}</b>.", True, False

    return "Бесплатный период закончился. Оформите подписку.", True, False
