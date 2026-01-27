from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from aiogram.types import BufferedInputFile

logger = logging.getLogger(__name__)

from app.db.database import Database
from app.db import queries
from app.config import Config
from app.services.reminders import (
    send_workout_reminder,
    ask_workout_confirmation,
    mark_missed_if_no_response,
)
from app.services.analytics import build_monthly_report, previous_month_range
from app.services.discipline import is_week_allowed
from app.services.payment import check_pending_payments, process_recurring_payments
from app.utils.charts import build_weight_chart


def _adjust_time(weekday: int, hour: int, minute: int, delta_minutes: int) -> tuple[int, int, int]:
    base = datetime(2000, 1, 3 + weekday, hour, minute)
    adjusted = base + timedelta(minutes=delta_minutes)
    return adjusted.weekday(), adjusted.hour, adjusted.minute


def _parse_time(time_str: str) -> tuple[int, int]:
    hour_str, minute_str = time_str.split(":")
    return int(hour_str), int(minute_str)


async def _reminder_job(
    bot: Bot, 
    tg_id: int, 
    tz: ZoneInfo, 
    week_type: str, 
    week_parity_offset: int,
    hours_before: int = 2
) -> None:
    workout_at = datetime.now(tz).replace(second=0, microsecond=0) + timedelta(hours=hours_before)
    if not is_week_allowed(workout_at, week_parity_offset, week_type):
        logger.debug(f"⏭️ Напоминание пропущено: неделя не подходит (week_type={week_type}, workout_at={workout_at})")
        return
    
    time_str = workout_at.strftime("%H:%M")
    if hours_before == 24:
        message = f"📅 Напоминание: тренировка завтра в {time_str}.\nПодготовьтесь заранее!"
    elif hours_before == 12:
        message = f"⏰ Напоминание: тренировка через 12 часов в {time_str}.\nНе забудьте подготовиться!"
    elif hours_before == 6:
        message = f"⏰ Напоминание: тренировка через 6 часов в {time_str}.\nПланируйте свой день!"
    elif hours_before == 3:
        message = f"⏰ Напоминание: тренировка через 3 часа в {time_str}.\nПриготовьте всё необходимое!"
    elif hours_before == 1:
        message = f"⏰ Напоминание: тренировка через 1 час в {time_str}.\nПочти время!"
    else:
        message = f"⏰ Напоминание: тренировка через {hours_before} часов в {time_str}.\nПодготовьтесь и будьте вовремя!"
    
    try:
        await bot.send_message(tg_id, message)
        logger.info(f"✅ Напоминание отправлено: tg_id={tg_id}, за {hours_before}ч до тренировки в {time_str} (week_type={week_type})")
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке напоминания пользователю {tg_id}: {e}", exc_info=True)


async def _confirmation_job(
    bot: Bot,
    tg_id: int,
    tz: ZoneInfo,
    workout_hour: int,
    workout_minute: int,
    week_type: str,
    week_parity_offset: int,
) -> None:
    now = datetime.now(tz)
    workout_at = now.replace(hour=workout_hour, minute=workout_minute, second=0, microsecond=0)
    if not is_week_allowed(workout_at, week_parity_offset, week_type):
        return
    await ask_workout_confirmation(bot, tg_id, workout_at)


async def _missed_job(
    db: Database,
    bot: Bot,
    user_id: int,
    tg_id: int,
    tz: ZoneInfo,
    workout_hour: int,
    workout_minute: int,
    week_type: str,
    week_parity_offset: int,
) -> None:
    now = datetime.now(tz)
    workout_at = now.replace(hour=workout_hour, minute=workout_minute, second=0, microsecond=0)
    if workout_at > now:
        workout_at -= timedelta(days=1)
    if not is_week_allowed(workout_at, week_parity_offset, week_type):
        return
    await mark_missed_if_no_response(db, bot, user_id, tg_id, workout_at)


async def _weekly_weight_job(bot: Bot, db: Database, tz: ZoneInfo) -> None:
    """Еженедельный запрос веса каждую неделю в понедельник"""
    logger.info("📅 Запуск еженедельного запроса веса (понедельник)")
    users = await queries.list_users(db)
    logger.info(f"👥 Найдено пользователей для уведомления: {len(users)}")
    
    for user in users:
        user_id = int(user["id"])
        tg_id = int(user["tg_id"])
        
        try:
            # Получаем последний вес для сравнения
            latest_weight = await queries.get_latest_weight(db, user_id)
            last_weight_text = ""
            if latest_weight:
                last_weight = float(latest_weight["weight"])
                last_date = datetime.fromisoformat(latest_weight["date"])
                days_ago = (datetime.now(tz) - last_date.replace(tzinfo=tz)).days
                if days_ago > 0:
                    last_weight_text = f"\n📊 Последний вес: <b>{last_weight:.1f} кг</b> ({days_ago} дн. назад)"
                logger.debug(f"📊 Пользователь {user_id}: последний вес {last_weight:.1f} кг ({days_ago} дн. назад)")
            
            await bot.send_message(
                tg_id,
                "📅 <b>Понедельник — день взвешивания!</b>\n\n"
                "⚖️ Введите текущий вес одним числом.\n\n"
                "Примеры:\n"
                "• <code>82.4</code>\n"
                "• <code>75</code>\n"
                "• <code>90.5</code>"
                + last_weight_text,
            )
            logger.info(f"✅ Уведомление о взвешивании отправлено пользователю {user_id} (tg_id={tg_id})")
        except Exception as e:
            logger.error(f"❌ Ошибка при отправке уведомления пользователю {user_id} (tg_id={tg_id}): {e}", exc_info=True)


async def _monthly_report_job(bot: Bot, db: Database, tz: ZoneInfo) -> None:
    users = await queries.list_users(db)
    report_start, report_end = previous_month_range(datetime.now(tz))
    for user in users:
        user_id = int(user["id"])
        tg_id = int(user["tg_id"])
        week_parity_offset = int(user.get("week_parity_offset") or 0)
        report = await build_monthly_report(db, user_id, report_start, report_end, week_parity_offset)

        start_weight_str = f"{report.start_weight:.1f} кг" if report.start_weight is not None else "нет данных"
        end_weight_str = f"{report.end_weight:.1f} кг" if report.end_weight is not None else "нет данных"
        diff_str = f"{report.diff:+.1f} кг" if report.diff is not None else "нет данных"
        diff_percent_str = f"{report.diff_percent:+.1f}%" if report.diff_percent is not None else "нет данных"
        
        message = (
            f"📊 <b>Месячный отчет</b>\n"
            f"📅 Период: {report_start.strftime('%m.%Y')}\n\n"
            f"⚖️ <b>Прогресс веса:</b>\n"
            f"   • Стартовый вес: {start_weight_str}\n"
            f"   • Текущий вес: {end_weight_str}\n"
            f"   • Изменение: {diff_str} ({diff_percent_str})\n\n"
            f"🏋️ <b>Тренировки:</b>\n"
            f"   ✅ Выполнено: {report.completed}\n"
            f"   ❌ Пропущено: {report.missed}\n\n"
            f"📈 <b>Дисциплина: {report.discipline_score:.1f}%</b>"
        )
        await bot.send_message(tg_id, message)

        if report.weights:
            chart = await build_weight_chart(report.weights)
            photo = BufferedInputFile(chart, filename="weight.png")
            await bot.send_photo(tg_id, photo, caption="График прогресса веса")

        if report.discipline_score < 70:
            await bot.send_message(
                tg_id,
                "⚠️ <b>Внимание!</b>\n\n"
                "Ваша дисциплина ниже 70%. Это сигнал, что вы теряете ритм.\n\n"
                "💪 <b>Исправьте ситуацию на этой неделе!</b>\n"
                "Помните: стабильность — ключ к успеху."
            )


def create_scheduler(tz: ZoneInfo) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=tz)
    return scheduler


def _remove_user_jobs(scheduler: AsyncIOScheduler, user_id: int) -> int:
    prefix = f"user:{user_id}:"
    removed_count = 0
    for job in scheduler.get_jobs():
        if job.id.startswith(prefix):
            scheduler.remove_job(job.id)
            removed_count += 1
    return removed_count


def schedule_user_jobs(
    scheduler: AsyncIOScheduler,
    db: Database,
    bot: Bot,
    user_id: int,
    tg_id: int,
    schedule: list[dict],
    week_parity_offset: int,
    tz: ZoneInfo,
) -> None:
    logger.info(f"📅 Настройка задач для пользователя: user_id={user_id}, tg_id={tg_id}, записей расписания={len(schedule)}")
    jobs_removed = _remove_user_jobs(scheduler, user_id)
    if jobs_removed > 0:
        logger.debug(f"🗑️ Удалено старых задач: {jobs_removed}")
    
    total_jobs = 0
    for entry in schedule:
        weekday = int(entry["weekday"])
        time_str = entry["time"]
        week_type = entry.get("week_type", "any")
        hour, minute = _parse_time(time_str)
        
        weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        logger.debug(f"  📋 Запись расписания: {weekday_names[weekday]} {time_str} (week_type={week_type})")

        # Напоминания: за 24ч, 12ч, 6ч, 3ч, 2ч, 1ч до тренировки
        reminder_times = [
            (-24 * 60, 24),  # За сутки
            (-12 * 60, 12),  # За 12 часов
            (-6 * 60, 6),    # За 6 часов
            (-3 * 60, 3),    # За 3 часа
            (-2 * 60, 2),    # За 2 часа
            (-60, 1),        # За 1 час
        ]
        
        for delta_minutes, hours_before in reminder_times:
            reminder_weekday, reminder_hour, reminder_minute = _adjust_time(weekday, hour, minute, delta_minutes)
            scheduler.add_job(
                _reminder_job,
                CronTrigger(day_of_week=reminder_weekday, hour=reminder_hour, minute=reminder_minute, timezone=tz),
                id=f"user:{user_id}:reminder:{hours_before}h:{weekday}:{time_str}:{week_type}",
                kwargs={
                    "bot": bot,
                    "tg_id": tg_id,
                    "tz": tz,
                    "week_type": week_type,
                    "week_parity_offset": week_parity_offset,
                    "hours_before": hours_before,
                },
                replace_existing=True,
            )
            total_jobs += 1
        
        scheduler.add_job(
            _confirmation_job,
            CronTrigger(day_of_week=weekday, hour=hour, minute=minute, timezone=tz),
            id=f"user:{user_id}:confirm:{weekday}:{time_str}:{week_type}",
            kwargs={
                "bot": bot,
                "tg_id": tg_id,
                "tz": tz,
                "workout_hour": hour,
                "workout_minute": minute,
                "week_type": week_type,
                "week_parity_offset": week_parity_offset,
            },
            replace_existing=True,
        )
        total_jobs += 1
        
        # Проверка пропуска через 3 часа после времени тренировки (180 минут)
        # Это даёт пользователям достаточно времени для ответа
        missed_weekday, missed_hour, missed_minute = _adjust_time(weekday, hour, minute, 180)
        scheduler.add_job(
            _missed_job,
            CronTrigger(day_of_week=missed_weekday, hour=missed_hour, minute=missed_minute, timezone=tz),
            id=f"user:{user_id}:missed:{weekday}:{time_str}:{week_type}",
            kwargs={
                "db": db,
                "bot": bot,
                "user_id": user_id,
                "tg_id": tg_id,
                "tz": tz,
                "workout_hour": hour,
                "workout_minute": minute,
                "week_type": week_type,
                "week_parity_offset": week_parity_offset,
            },
            replace_existing=True,
        )
        total_jobs += 1
    
    logger.info(f"✅ Задачи для пользователя {user_id} созданы: всего {total_jobs} задач ({len(schedule)} записей расписания × ~8 задач на запись)")


async def _check_pending_payments_job(db: Database, tz: ZoneInfo, config: Config) -> None:
    """Проверка статусов pending платежей."""
    await check_pending_payments(db=db, tz=tz, config=config)


async def _recurring_payments_job(bot: Bot, db: Database, tz: ZoneInfo, config: Config) -> None:
    """Обработка рекуррентных платежей."""
    await process_recurring_payments(db=db, bot=bot, tz=tz, config=config)


def schedule_global_jobs(scheduler: AsyncIOScheduler, db: Database, bot: Bot, tz: ZoneInfo, config: Config) -> None:
    logger.info("📅 Настройка глобальных задач планировщика")
    
    scheduler.add_job(
        _weekly_weight_job,
        CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=tz),
        id="global:weekly-weight",
        kwargs={"bot": bot, "db": db, "tz": tz},
        replace_existing=True,
    )
    logger.info("✅ Задача 'Еженедельное взвешивание' запланирована: каждый понедельник в 08:00")
    
    scheduler.add_job(
        _monthly_report_job,
        CronTrigger(day=1, hour=9, minute=0, timezone=tz),
        id="global:monthly-report",
        kwargs={"bot": bot, "db": db, "tz": tz},
        replace_existing=True,
    )
    logger.info("✅ Задача 'Месячный отчет' запланирована: 1-го числа каждого месяца в 09:00")
    
    # Проверка pending платежей каждую минуту
    scheduler.add_job(
        _check_pending_payments_job,
        CronTrigger(minute="*", timezone=tz),  # Каждую минуту
        id="global:check-pending-payments",
        kwargs={"db": db, "tz": tz, "config": config},
        replace_existing=True,
    )
    logger.info("✅ Задача 'Проверка pending платежей' запланирована: каждую минуту")
    
    scheduler.add_job(
        _recurring_payments_job,
        CronTrigger(hour=2, minute=0, timezone=tz),  # Каждый день в 02:00
        id="global:recurring-payments",
        kwargs={"bot": bot, "db": db, "tz": tz, "config": config},
        replace_existing=True,
    )
    logger.info("✅ Задача 'Рекуррентные платежи' запланирована: каждый день в 02:00")


async def load_all_schedules(scheduler: AsyncIOScheduler, db: Database, bot: Bot, tz: ZoneInfo) -> None:
    logger.info("📋 Загрузка расписаний всех пользователей")
    users = await queries.list_users(db)
    logger.info(f"👥 Найдено пользователей: {len(users)}")
    
    total_jobs = 0
    for user in users:
        user_id = int(user["id"])
        tg_id = int(user["tg_id"])
        week_parity_offset = int(user.get("week_parity_offset") or 0)
        schedule = await queries.get_workout_schedule(db, user_id)
        
        jobs_before = len([j for j in scheduler.get_jobs() if j.id.startswith(f"user:{user_id}:")])
        schedule_user_jobs(scheduler, db, bot, user_id, tg_id, schedule, week_parity_offset, tz)
        jobs_after = len([j for j in scheduler.get_jobs() if j.id.startswith(f"user:{user_id}:")])
        jobs_added = jobs_after - jobs_before
        total_jobs += jobs_added
        
        logger.info(f"✅ Пользователь {user_id}: загружено {len(schedule)} записей расписания, создано {jobs_added} задач")
    
    logger.info(f"📊 Всего создано задач для пользователей: {total_jobs}")
