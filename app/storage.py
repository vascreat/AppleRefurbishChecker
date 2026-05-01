"""SQLite storage for monitoring tasks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from app.config import DEFAULT_INTERVAL_MINUTES


class TaskStorage:
    """Simple repository class for task CRUD operations."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._backup_existing_db()
        self._initialize()

    def _backup_existing_db(self) -> None:
        """Create a rolling backup before migrations when a DB already exists."""
        if not self._db_path.exists() or self._db_path.stat().st_size == 0:
            return

        backup_dir = self._db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / f"tasks-{timestamp}.db"
        shutil.copy2(self._db_path, backup_path)

        backups = sorted(backup_dir.glob("tasks-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old_backup in backups[10:]:
            old_backup.unlink(missing_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """Create a SQLite connection configured for dict-like row access."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        """Create the tasks table if it does not already exist."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    name TEXT PRIMARY KEY,
                    creator_id INTEGER NOT NULL,
                    creator_chat_id INTEGER NOT NULL,
                    url TEXT,
                    keywords TEXT NOT NULL,
                    min_price REAL,
                    max_price REAL,
                    interval_minutes INTEGER NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            # Lightweight migration for old DBs created before price fields were added.
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
            }
            if "min_price" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN min_price REAL")
            if "max_price" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN max_price REAL")
            conn.commit()

    def create_task(self, name: str, creator_id: int, creator_chat_id: int) -> bool:
        """Create a new task with default values, returning False on duplicates."""
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO tasks (
                        name,
                        creator_id,
                        creator_chat_id,
                        url,
                        keywords,
                        min_price,
                        max_price,
                        interval_minutes,
                        status
                    )
                    VALUES (?, ?, ?, NULL, ?, NULL, NULL, ?, 'stopped')
                    """,
                    (name, creator_id, creator_chat_id, "[]", DEFAULT_INTERVAL_MINUTES),
                )
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def task_exists(self, name: str) -> bool:
        """Return True if a task with the given name exists."""
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM tasks WHERE name = ?", (name,)).fetchone()
            return row is not None

    def get_task(self, name: str) -> dict[str, Any] | None:
        """Return one task as a dictionary, or None when missing."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE name = ?", (name,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_tasks(self) -> list[dict[str, Any]]:
        """Return all tasks ordered by name."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY name ASC").fetchall()
        return [self._row_to_task(row) for row in rows]

    def update_url(self, name: str, url: str) -> bool:
        """Update the URL of a task and return True when a row is updated."""
        return self._update_field(name, "url", url)

    def update_keywords(self, name: str, keywords: list[str]) -> bool:
        """Store a de-duplicated keyword list as JSON."""
        return self._update_field(name, "keywords", json.dumps(keywords))

    def update_interval(self, name: str, minutes: int) -> bool:
        """Update the check interval (minutes) of a task."""
        return self._update_field(name, "interval_minutes", minutes)

    def update_price_range(
        self,
        name: str,
        min_price: float | None,
        max_price: float | None,
    ) -> bool:
        """Update price range bounds for a task."""
        with self._connect() as conn:
            result = conn.execute(
                "UPDATE tasks SET min_price = ?, max_price = ? WHERE name = ?",
                (min_price, max_price, name),
            )
            conn.commit()
            return result.rowcount > 0

    def update_status(self, name: str, status: str) -> bool:
        """Set task status to running or stopped."""
        return self._update_field(name, "status", status)

    def delete_task(self, name: str) -> bool:
        """Delete a task by name and return True if it existed."""
        with self._connect() as conn:
            result = conn.execute("DELETE FROM tasks WHERE name = ?", (name,))
            conn.commit()
            return result.rowcount > 0

    def _update_field(self, name: str, field_name: str, value: Any) -> bool:
        """Internal helper for single-field updates."""
        with self._connect() as conn:
            result = conn.execute(
                f"UPDATE tasks SET {field_name} = ? WHERE name = ?",
                (value, name),
            )
            conn.commit()
            return result.rowcount > 0

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite row into an application task dictionary."""
        return {
            "name": row["name"],
            "creator_id": row["creator_id"],
            "creator_chat_id": row["creator_chat_id"],
            "url": row["url"],
            "keywords": json.loads(row["keywords"]),
            "min_price": row["min_price"],
            "max_price": row["max_price"],
            "interval_minutes": row["interval_minutes"],
            "status": row["status"],
        }
