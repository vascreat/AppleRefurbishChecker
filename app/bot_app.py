"""Build and run the Telegram bot application."""

from __future__ import annotations

import logging

from telegram.ext import Application

from app.config import get_bot_token, get_database_path
from app.handlers import register_handlers
from app.monitor import MonitorService
from app.storage import TaskStorage


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def run_bot() -> None:
    """Create services, register handlers, and start polling."""
    token = get_bot_token()
    storage = TaskStorage(get_database_path())

    application = Application.builder().token(token).build()
    monitor = MonitorService(application, storage)
    register_handlers(application, storage, monitor)

    async def _post_init(app: Application) -> None:
        """Resume any tasks that were running before restart."""
        await monitor.start_running_tasks_from_storage()

    async def _post_shutdown(app: Application) -> None:
        """Stop all background jobs during graceful shutdown."""
        monitor.stop_all()

    application.post_init = _post_init
    application.post_shutdown = _post_shutdown
    application.run_polling(close_loop=False)
