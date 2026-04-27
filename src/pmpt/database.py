from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


class SQLiteDatabase:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @staticmethod
    def default_home() -> Path:
        env_home = os.environ.get("PMPT_HOME")
        if env_home:
            return Path(env_home).expanduser()
        return Path.home() / "Library" / "Application Support" / "pmpt"

    @classmethod
    def default_path(cls) -> Path:
        return cls.default_home() / "prompts.sqlite3"

    @staticmethod
    def now() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompts (
                    name TEXT PRIMARY KEY,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tags (
                    name TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_tags (
                    prompt_name TEXT NOT NULL,
                    tag_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (prompt_name, tag_name),
                    FOREIGN KEY (prompt_name) REFERENCES prompts(name) ON DELETE CASCADE,
                    FOREIGN KEY (tag_name) REFERENCES tags(name) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    used_at TEXT NOT NULL,
                    detail TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_usage (
                    event_id INTEGER NOT NULL,
                    prompt_name TEXT NOT NULL,
                    PRIMARY KEY (event_id, prompt_name),
                    FOREIGN KEY (event_id) REFERENCES usage_events(id) ON DELETE CASCADE,
                    FOREIGN KEY (prompt_name) REFERENCES prompts(name) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_name TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    FOREIGN KEY (prompt_name) REFERENCES prompts(name) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prompt_name TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (prompt_name) REFERENCES prompts(name) ON DELETE CASCADE
                )
                """
            )


def default_home() -> Path:
    return SQLiteDatabase.default_home()


def database_path() -> Path:
    return SQLiteDatabase.default_path()
