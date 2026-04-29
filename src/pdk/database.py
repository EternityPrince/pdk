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
        env_home = os.environ.get("PDK_HOME") or os.environ.get("PMPT_HOME")
        if env_home:
            return Path(env_home).expanduser()
        support_dir = Path.home() / "Library" / "Application Support"
        home = support_dir / "Prompt Deck"
        legacy_home = support_dir / "pmpt"
        if legacy_home.exists() and not home.exists():
            return legacy_home
        return home

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
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(prompts)").fetchall()
            }
            if "project_id" not in columns:
                conn.execute("ALTER TABLE prompts ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL")
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
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER,
                    title TEXT,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS note_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    note_id INTEGER NOT NULL,
                    title TEXT,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prompts_project_id ON prompts(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_project_id ON notes(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_note_versions_note_id ON note_versions(note_id)")
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
