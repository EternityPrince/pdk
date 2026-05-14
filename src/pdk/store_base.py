from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .database import SQLiteDatabase
from .models import Note, Prompt, Project, TagSet, UsageAction, VersionReason


class PromptExistsError(Exception):
    pass


class PromptNotFoundError(Exception):
    pass


class ProjectExistsError(Exception):
    pass


class NamedProjectNotFoundError(Exception):
    pass


class NoteNotFoundError(Exception):
    pass


class PromptStoreBase:
    def __init__(self, path: Path | None = None) -> None:
        self._db = SQLiteDatabase(path)
        self.path = self._db.path

    def _prompt_exists(self, conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute("SELECT 1 FROM prompts WHERE name = ?", (name,)).fetchone()
        return row is not None

    def _save_version(
        self,
        conn: sqlite3.Connection,
        name: str,
        body: str,
        reason: VersionReason,
    ) -> None:
        conn.execute(
            """
            INSERT INTO prompt_versions (prompt_name, body, created_at, reason)
            VALUES (?, ?, ?, ?)
            """,
            (name, body, self._db.now(), reason.value),
        )

    def _normalize_tags(self, tags: Iterable[str]) -> tuple[str, ...]:
        return TagSet.from_values(tags).names

    @staticmethod

    def _project_from_row(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod

    def _note_from_row(row: sqlite3.Row) -> Note:
        return Note(
            id=row["id"],
            project_id=row["project_id"],
            project_name=row["project_name"],
            title=row["title"],
            body=row["body"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _project_id_for(self, conn: sqlite3.Connection, name: str) -> int:
        row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise NamedProjectNotFoundError(name)
        return int(row["id"])

    def _tags_for(self, conn: sqlite3.Connection, name: str) -> tuple[str, ...]:
        rows = conn.execute(
            """
            SELECT tag_name
            FROM prompt_tags
            WHERE prompt_name = ?
            ORDER BY tag_name COLLATE NOCASE
            """,
            (name,),
        ).fetchall()
        return tuple(row["tag_name"] for row in rows)

    def _prompt_from_row(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Prompt:
        return Prompt(
            name=row["name"],
            body=row["body"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            project_id=row["project_id"],
            project_name=row["project_name"],
            tags=self._tags_for(conn, row["name"]),
        )

    def _apply_tags(
        self,
        conn: sqlite3.Connection,
        prompt_name: str,
        tags: Iterable[str],
    ) -> None:
        now = self._db.now()
        for tag in self._normalize_tags(tags):
            conn.execute(
                "INSERT OR IGNORE INTO tags (name, created_at) VALUES (?, ?)",
                (tag, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO prompt_tags (prompt_name, tag_name, created_at)
                VALUES (?, ?, ?)
                """,
                (prompt_name, tag, now),
            )

    def record_usage(
        self,
        action: UsageAction,
        prompt_names: Iterable[str] = (),
        *,
        detail: str | None = None,
    ) -> None:
        with self._db.connect() as conn:
            event_id = self._record_usage(conn, action, prompt_names, detail=detail)
            if event_id is None:
                conn.rollback()

    def import_usage(
        self,
        action: UsageAction,
        prompt_names: Iterable[str] = (),
        *,
        detail: str | None = None,
        used_at: str,
    ) -> None:
        with self._db.connect() as conn:
            names = list(dict.fromkeys(prompt_names))
            for name in names:
                if not self._prompt_exists(conn, name):
                    raise PromptNotFoundError(name)
            cursor = conn.execute(
                "INSERT INTO usage_events (action, used_at, detail) VALUES (?, ?, ?)",
                (action.value, used_at, detail),
            )
            event_id = int(cursor.lastrowid)
            conn.executemany(
                "INSERT INTO prompt_usage (event_id, prompt_name) VALUES (?, ?)",
                [(event_id, name) for name in names],
            )

    def _record_usage(
        self,
        conn: sqlite3.Connection,
        action: UsageAction,
        prompt_names: Iterable[str] = (),
        *,
        detail: str | None = None,
    ) -> int | None:
        names = list(dict.fromkeys(prompt_names))
        for name in names:
            if not self._prompt_exists(conn, name):
                return None
        cursor = conn.execute(
            "INSERT INTO usage_events (action, used_at, detail) VALUES (?, ?, ?)",
            (action.value, self._db.now(), detail),
        )
        event_id = int(cursor.lastrowid)
        conn.executemany(
            "INSERT INTO prompt_usage (event_id, prompt_name) VALUES (?, ?)",
            [(event_id, name) for name in names],
        )
        return event_id

    # Project operations
