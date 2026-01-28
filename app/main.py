from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot import create_bot
from app.config import load_config, Config
from app.db.database import Database, init_db
from app.db import queries
from app.handlers import menu, start, schedule, workouts, weight, reports, profile, admin, calories, subscription
from app.scheduler import create_scheduler, schedule_global_jobs, load_all_schedules
from app.services.access import has_access, is_admin, PRODUCT_DESCRIPTION, get_product_price_text
from app.utils.keyboards import paywall_kb


class ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[94m",      # Синий
        "INFO": "\033[92m",       # Зеленый
        "WARNING": "\033[93m",    # Желтый
        "ERROR": "\033[91m",       # Красный
        "CRITICAL": "\033[95m",    # Фиолетовый
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        color = self.COLORS.get(level, "")
        colored_level = f"{color}{self.BOLD}{level}{self.RESET}" if color else level
        
        # Форматируем время в читаемом виде
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Формируем основную строку лога
        parts = [
            f"[{timestamp}]",
            f"{colored_level:8}",
            f"│",
        ]
        
        # Добавляем информацию о модуле и функции
        if record.module and record.funcName:
            parts.append(f"{record.module}.{record.funcName}")
        
        # Добавляем номер строки
        if record.lineno:
            parts.append(f"(line {record.lineno})")
        
        parts.append("│")
        
        # Добавляем сообщение
        message = record.getMessage()
        parts.append(message)
        
        # Добавляем информацию об исключении, если есть
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            parts.append(f"\n{'─' * 80}\n{exc_text}")
        
        return " ".join(parts)


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)


class ContextMiddleware(BaseMiddleware):
    def __init__(self, db: Database, scheduler, tz: ZoneInfo, config: Config) -> None:
        self._db = db
        self._scheduler = scheduler
        self._tz = tz
        self._config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["db"] = self._db
        data["scheduler"] = self._scheduler
        data["tz"] = self._tz
        data["config"] = self._config
        return await handler(event, data)


async def _paywall_text(db: Database) -> str:
    product_price = await get_product_price_text(db)
    return (
        "⏱ <b>Бесплатный период (5 дней) закончился.</b>\n\n"
        "Оформите подписку:\n\n"
        f"{PRODUCT_DESCRIPTION}\n\n"
        f"{product_price}\n\n"
        "Нажмите кнопку ниже для оплаты."
    )


class AccessMiddleware(BaseMiddleware):
    """Проверка доступа: триал 5 дней, подписка, админы всегда бесплатно."""

    def __init__(self, db: Database, tz: ZoneInfo, config: Config) -> None:
        self._db = db
        self._tz = tz
        self._config = config

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        db = self._db
        tz = self._tz
        config = self._config

        user_tg = None
        if isinstance(event, Message) and event.from_user:
            user_tg = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_tg = event.from_user
        if not user_tg:
            return await handler(event, data)

        tg_id = user_tg.id
        if is_admin(tg_id, config):
            return await handler(event, data)

        if isinstance(event, Message) and event.text:
            txt = event.text.strip().lower()
            if txt.startswith("/start") or txt.startswith("/tariff"):
                return await handler(event, data)
        if isinstance(event, CallbackQuery) and event.data and event.data.startswith("pay:"):
            return await handler(event, data)

        u = await queries.get_user_by_tg_id(db, tg_id)
        if not u:
            return await handler(event, data)

        if await has_access(db, tg_id, u, config, tz):
            return await handler(event, data)

        from app.services.access import get_subscription_price_rub
        price = await get_subscription_price_rub(db)
        kb = paywall_kb(price=price).as_markup()
        text = await _paywall_text(db)
        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.answer(text, reply_markup=kb)
        else:
            await event.answer(text, reply_markup=kb)
        return None


async def main() -> None:
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("=" * 80)
        logger.info("🚀 Запуск Discipline Bot")
        logger.info("=" * 80)
        
        config = load_config()
        setup_logging(config.log_level)
        logger.info(f"✅ Конфигурация загружена: timezone={config.timezone}, log_level={config.log_level}")

        tz = ZoneInfo(config.timezone)
        config.db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Путь к БД: {config.db_path}")
        
        db = Database(str(config.db_path))
        await db.connect()
        logger.info("✅ Подключение к базе данных установлено")
        
        await init_db(db)
        logger.info("✅ База данных инициализирована")

        bot = create_bot(config)
        logger.info("✅ Telegram бот создан")

        # Устанавливаем экземпляр бота для отправки уведомлений о платежах
        from app.services.payment import set_bot_instance
        set_bot_instance(bot)
        logger.info("✅ ЮMoney SDK готов к работе")
        
        scheduler = create_scheduler(tz)
        logger.info("✅ Планировщик задач создан")

        dp = Dispatcher(storage=MemoryStorage())
        dp.message.middleware(ContextMiddleware(db, scheduler, tz, config))
        dp.message.middleware(AccessMiddleware(db, tz, config))
        dp.callback_query.middleware(ContextMiddleware(db, scheduler, tz, config))
        dp.callback_query.middleware(AccessMiddleware(db, tz, config))
        logger.info("✅ Middleware настроен")

        dp.include_router(start.router)
        dp.include_router(profile.router)
        dp.include_router(menu.router)
        dp.include_router(schedule.router)
        dp.include_router(workouts.router)
        dp.include_router(weight.router)
        dp.include_router(calories.router)
        dp.include_router(reports.router)
        dp.include_router(admin.router)
        dp.include_router(subscription.router)
        logger.info("✅ Все роутеры подключены: start, profile, menu, schedule, workouts, weight, calories, reports, admin, subscription")

        schedule_global_jobs(scheduler, db, bot, tz, config)
        logger.info("✅ Глобальные задачи запланированы (еженедельное взвешивание, месячные отчеты, напоминания о подписке)")
        
        await load_all_schedules(scheduler, db, bot, tz)
        logger.info("✅ Расписания всех пользователей загружены")
        
        scheduler.start()
        logger.info("✅ Планировщик задач запущен")

        # Webhook сервер не используется при проверке статусов через SDK
        
        logger.info("=" * 80)
        logger.info("🎯 Бот готов к работе и ожидает обновлений")
        logger.info("=" * 80)

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.critical(f"❌ КРИТИЧЕСКАЯ ОШИБКА при запуске бота: {e}", exc_info=True)
        raise
    finally:
        logger.info("🛑 Завершение работы бота...")
        scheduler.shutdown(wait=False)
        logger.info("✅ Планировщик задач остановлен")
        await db.close()
        logger.info("✅ Соединение с базой данных закрыто")
        await bot.session.close()
        logger.info("✅ Сессия бота закрыта")
        logger.info("👋 Бот завершил работу")


if __name__ == "__main__":
    asyncio.run(main())
