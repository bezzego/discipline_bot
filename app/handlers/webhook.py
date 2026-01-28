"""HTTP endpoint (не используется, оставлен для совместимости)."""

from __future__ import annotations

import logging
from aiohttp import web

logger = logging.getLogger(__name__)


async def quickpay_webhook_handler(request: web.Request) -> web.Response:
    """
    Обработчик HTTP-уведомлений от ЮMoney Quickpay.
    Сейчас не используется, так как статусы проверяются через SDK.
    """
    try:
        logger.warning("⚠️ Получен webhook, но обработчик отключен (используется SDK).")
        return web.Response(status=410, text="Webhook is disabled")

    except Exception as e:
        logger.error(f"❌ Ошибка при обработке webhook: {e}", exc_info=True)
        return web.Response(status=500, text="Internal server error")
