"""Configuration helpers for environment-driven bot settings."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_INTERVAL_MINUTES = 30
MIN_INTERVAL_MINUTES = 10
MAX_INTERVAL_MINUTES = 720


def get_bot_token() -> str:
    """Read BOT_TOKEN from environment and raise a clear error if missing."""
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN is not set. Export BOT_TOKEN in your environment before running the bot."
        )
    return token


def get_database_path() -> Path:
    """Resolve the SQLite database path from env, creating parent directories if needed."""
    raw_path = os.getenv("TASKS_DB_PATH", "data/tasks.db")
    db_path = Path(raw_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path
