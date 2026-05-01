"""Telegram command handlers for task management."""

from __future__ import annotations

from urllib.parse import urlparse

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app.config import MAX_INTERVAL_MINUTES, MIN_INTERVAL_MINUTES
from app.monitor import MonitorService
from app.storage import TaskStorage


async def _reply(update: Update, text: str) -> None:
    """Safely send a text reply when an effective message is available."""
    message = update.effective_message
    if not message:
        return
    await message.reply_text(text)


def _get_user_id(update: Update) -> int | None:
    """Return user id when available on the update."""
    user = update.effective_user
    if not user:
        return None
    return user.id


def _get_chat_id(update: Update) -> int | None:
    """Return chat id when available on the update."""
    chat = update.effective_chat
    if not chat:
        return None
    return chat.id


def register_handlers(application: Application, storage: TaskStorage, monitor: MonitorService) -> None:
    """Register all command handlers with the Telegram application."""
    application.bot_data["storage"] = storage
    application.bot_data["monitor"] = monitor

    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("task", task_command))
    application.add_handler(CommandHandler(["checklink", "checkLink"], check_link_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler(["rmkeyword", "removekeyword"], remove_keyword_command))
    application.add_handler(CommandHandler(["clearkeywords", "clearkw"], clear_keywords_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CommandHandler("interval", interval_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler(["rm", "remove"], remove_command))
    application.add_handler(CommandHandler("list", list_command))


def _get_services(context: ContextTypes.DEFAULT_TYPE) -> tuple[TaskStorage, MonitorService]:
    """Fetch shared service instances from bot_data."""
    storage = context.application.bot_data["storage"]
    monitor = context.application.bot_data["monitor"]
    return storage, monitor


def _is_valid_url(url: str) -> bool:
    """Basic URL validation for HTTP/HTTPS links."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _parse_keywords(raw: str) -> list[str]:
    """Parse comma-separated keywords while removing blanks and duplicates."""
    unique: dict[str, str] = {}
    for item in raw.split(","):
        keyword = item.strip()
        if not keyword:
            continue
        unique.setdefault(keyword.lower(), keyword)
    return list(unique.values())


def _can_modify(user_id: int, task: dict) -> bool:
    """Allow only the task creator to modify task configuration and lifecycle."""
    return user_id == task["creator_id"]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start and /start <task_name> (start monitoring)."""
    args = context.args or []
    if not args:
        await help_command(update, context)
        return

    storage, monitor = _get_services(context)
    user_id = _get_user_id(update)
    if user_id is None:
        return

    task_name = args[0].strip()
    task = storage.get_task(task_name)
    if not task:
        await _reply(update, f"Task '{task_name}' does not exist.")
        return

    if not _can_modify(user_id, task):
        await _reply(update, "Only the creator can start this task.")
        return

    if not task["url"] or not task["keywords"]:
        await _reply(
            update,
            "Cannot start task. You must set both URL and keywords first."
        )
        return

    storage.update_status(task_name, "running")
    monitor.start_task(task_name)
    await _reply(update, f"Task '{task_name}' is now running.")


async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a new task with default values."""
    args = context.args or []
    if len(args) != 1:
        await _reply(update, "Usage: /task <task_name>")
        return

    task_name = args[0].strip()
    user_id = _get_user_id(update)
    chat_id = _get_chat_id(update)
    if user_id is None or chat_id is None:
        return

    storage, _ = _get_services(context)

    created = storage.create_task(
        task_name,
        creator_id=user_id,
        creator_chat_id=chat_id,
    )
    if not created:
        await _reply(update, f"Task '{task_name}' already exists.")
        return

    await _reply(
        update,
        f"Task '{task_name}' created. Set URL with /checklink and keywords with /search."
    )


async def check_link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Assign a target URL to an existing task."""
    args = context.args or []
    if len(args) != 2:
        await _reply(update, "Usage: /checklink <task_name> <url>")
        return

    task_name = args[0].strip()
    url = args[1].strip()
    if not _is_valid_url(url):
        await _reply(update, "Invalid URL. Use a full HTTP/HTTPS URL.")
        return

    storage, _ = _get_services(context)
    user_id = _get_user_id(update)
    if user_id is None:
        return

    task = storage.get_task(task_name)
    if not task:
        await _reply(update, f"Task '{task_name}' does not exist.")
        return

    if not _can_modify(user_id, task):
        await _reply(update, "Only the creator can modify this task.")
        return

    storage.update_url(task_name, url)
    await _reply(update, f"URL set for '{task_name}'.")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set or extend keyword list for a task without duplicates."""
    args = context.args or []
    if len(args) < 2:
        await _reply(update, "Usage: /search <task_name> <kw1, kw2, ...>")
        return

    task_name = args[0].strip()
    raw_keywords = " ".join(args[1:]).strip()
    new_keywords = _parse_keywords(raw_keywords)
    if not new_keywords:
        await _reply(update, "Provide at least one valid keyword.")
        return

    storage, _ = _get_services(context)
    user_id = _get_user_id(update)
    if user_id is None:
        return

    task = storage.get_task(task_name)
    if not task:
        await _reply(update, f"Task '{task_name}' does not exist.")
        return

    if not _can_modify(user_id, task):
        await _reply(update, "Only the creator can modify this task.")
        return

    merged: dict[str, str] = {kw.lower(): kw for kw in task["keywords"]}
    for keyword in new_keywords:
        merged.setdefault(keyword.lower(), keyword)

    final_keywords = list(merged.values())
    storage.update_keywords(task_name, final_keywords)
    await _reply(
        update,
        f"Keywords updated for '{task_name}': {', '.join(final_keywords)}"
    )


async def interval_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set task interval in minutes within accepted limits."""
    args = context.args or []
    if len(args) != 2:
        await _reply(update, "Usage: /interval <task_name> <minutes>")
        return

    task_name = args[0].strip()
    minutes_raw = args[1].strip()

    try:
        minutes = int(minutes_raw)
    except ValueError:
        await _reply(update, "Minutes must be an integer.")
        return

    if minutes < MIN_INTERVAL_MINUTES or minutes > MAX_INTERVAL_MINUTES:
        await _reply(
            update,
            f"Interval must be between {MIN_INTERVAL_MINUTES} and {MAX_INTERVAL_MINUTES} minutes."
        )
        return

    storage, _ = _get_services(context)
    user_id = _get_user_id(update)
    if user_id is None:
        return

    task = storage.get_task(task_name)
    if not task:
        await _reply(update, f"Task '{task_name}' does not exist.")
        return

    if not _can_modify(user_id, task):
        await _reply(update, "Only the creator can modify this task.")
        return

    if task["status"] == "running":
        await _reply(update, "Stop the task before changing interval.")
        return

    storage.update_interval(task_name, minutes)
    await _reply(update, f"Interval for '{task_name}' set to {minutes} minutes.")


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set optional item price range for matching: /price <task_name> <min> <max>."""
    args = context.args or []
    if len(args) != 3:
        await _reply(update, "Usage: /price <task_name> <min_price> <max_price>")
        return

    task_name = args[0].strip()
    min_raw = args[1].strip()
    max_raw = args[2].strip()

    try:
        min_price = float(min_raw)
        max_price = float(max_raw)
    except ValueError:
        await _reply(update, "Min and max price must be numbers.")
        return

    if min_price < 0 or max_price < 0:
        await _reply(update, "Price values must be non-negative.")
        return

    if min_price > max_price:
        await _reply(update, "min_price must be less than or equal to max_price.")
        return

    storage, _ = _get_services(context)
    user_id = _get_user_id(update)
    if user_id is None:
        return

    task = storage.get_task(task_name)
    if not task:
        await _reply(update, f"Task '{task_name}' does not exist.")
        return

    if not _can_modify(user_id, task):
        await _reply(update, "Only the creator can modify this task.")
        return

    if task["status"] == "running":
        await _reply(update, "Stop the task before changing price range.")
        return

    storage.update_price_range(task_name, min_price, max_price)
    await _reply(
        update,
        f"Price range for '{task_name}' set to {min_price:.2f} - {max_price:.2f}."
    )


async def remove_keyword_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove specific keywords from a task: /rmkeyword <task_name> <kw1, kw2, ...>"""
    args = context.args or []
    if len(args) < 2:
        await _reply(update, "Usage: /rmkeyword <task_name> <kw1, kw2, ...>")
        return

    task_name = args[0].strip()
    to_remove = {kw.strip().lower() for kw in " ".join(args[1:]).split(",") if kw.strip()}
    if not to_remove:
        await _reply(update, "Provide at least one keyword to remove.")
        return

    storage, _ = _get_services(context)
    user_id = _get_user_id(update)
    if user_id is None:
        return

    task = storage.get_task(task_name)
    if not task:
        await _reply(update, f"Task '{task_name}' does not exist.")
        return

    if not _can_modify(user_id, task):
        await _reply(update, "Only the creator can modify this task.")
        return

    remaining = [kw for kw in task["keywords"] if kw.lower() not in to_remove]
    removed = [kw for kw in task["keywords"] if kw.lower() in to_remove]

    if not removed:
        await _reply(update, "None of those keywords were found in the task.")
        return

    storage.update_keywords(task_name, remaining)
    removed_str = ", ".join(removed)
    remaining_str = ", ".join(remaining) if remaining else "none"
    await _reply(
        update,
        f"Removed from '{task_name}': {removed_str}\nRemaining keywords: {remaining_str}"
    )


async def clear_keywords_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove all keywords from a task: /clearkeywords <task_name>"""
    args = context.args or []
    if len(args) != 1:
        await _reply(update, "Usage: /clearkeywords <task_name>")
        return

    task_name = args[0].strip()
    storage, _ = _get_services(context)
    user_id = _get_user_id(update)
    if user_id is None:
        return

    task = storage.get_task(task_name)
    if not task:
        await _reply(update, f"Task '{task_name}' does not exist.")
        return

    if not _can_modify(user_id, task):
        await _reply(update, "Only the creator can modify this task.")
        return

    if task["status"] == "running":
        await _reply(update, "Stop the task before clearing keywords.")
        return

    storage.update_keywords(task_name, [])
    await _reply(update, f"All keywords cleared from '{task_name}'.")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stop a running task."""
    args = context.args or []
    if len(args) != 1:
        await _reply(update, "Usage: /stop <task_name>")
        return

    task_name = args[0].strip()
    user_id = _get_user_id(update)
    if user_id is None:
        return

    storage, monitor = _get_services(context)
    task = storage.get_task(task_name)
    if not task:
        await _reply(update, f"Task '{task_name}' does not exist.")
        return

    if not _can_modify(user_id, task):
        await _reply(update, "Only the creator can stop this task.")
        return

    storage.update_status(task_name, "stopped")
    monitor.stop_task(task_name)
    await _reply(update, f"Task '{task_name}' stopped.")


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a task permanently."""
    args = context.args or []
    if len(args) != 1:
        await _reply(update, "Usage: /rm <task_name>")
        return

    task_name = args[0].strip()
    user_id = _get_user_id(update)
    if user_id is None:
        return

    storage, monitor = _get_services(context)
    task = storage.get_task(task_name)
    if not task:
        await _reply(update, f"Task '{task_name}' does not exist.")
        return

    if not _can_modify(user_id, task):
        await _reply(update, "Only the creator can delete this task.")
        return

    monitor.stop_task(task_name)
    storage.delete_task(task_name)
    await _reply(update, f"Task '{task_name}' removed.")


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display all tasks with URL, keywords, interval, and status."""
    storage, _ = _get_services(context)
    tasks = storage.list_tasks()
    if not tasks:
        await _reply(update, "No tasks found.")
        return

    lines: list[str] = []
    for task in tasks:
        url = task["url"] if task["url"] else "not given"
        keywords = ", ".join(task["keywords"]) if task["keywords"] else "not given"
        if task["min_price"] is None or task["max_price"] is None:
            price_range = "not given"
        else:
            price_range = f"{task['min_price']:.2f}-{task['max_price']:.2f}"
        lines.append(
            f"- {task['name']} | URL: {url} | Keywords: {keywords} | "
            f"Price: {price_range} | Interval: {task['interval_minutes']} min | Status: {task['status']}"
        )

    await _reply(update, "\n".join(lines))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available commands with concise usage explanations."""
    await _reply(
        update,
        "Available commands:\n"
        "/task <task_name> - Create a new empty task.\n"
        "/checklink <task_name> <url> - Set the page URL to monitor.\n"
        "/search <task_name> <kw1, kw2, ...> - Add keywords to monitor (no duplicates).\n"
        "/rmkeyword <task_name> <kw1, kw2, ...> - Remove specific keywords from a task.\n"
        "/clearkeywords <task_name> - Remove all keywords from a task.\n"
        "/price <task_name> <min_price> <max_price> - Require item price to be within range.\n"
        f"/interval <task_name> <minutes> - Set check interval ({MIN_INTERVAL_MINUTES}-{MAX_INTERVAL_MINUTES} min).\n"
        "/start <task_name> - Start monitoring a configured task.\n"
        "/stop <task_name> - Stop a running task.\n"
        "/rm <task_name> - Delete a task permanently.\n"
        "/list - Show all tasks and their current settings.\n"
        "/help - Show this help message."
    )
