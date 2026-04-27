from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .database import SQLiteDatabase, database_path, default_home
from .models import (
    Feedback,
    Prompt,
    PromptDraft,
    PromptSearch,
    PromptStats,
    PromptVersion,
    TagSet,
    TagSummary,
    UsageAction,
    UsageEvent,
    VersionReason,
)


class PromptExistsError(Exception):
    pass


class PromptNotFoundError(Exception):
    pass


class PromptStore:
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

    def add(
        self,
        name: str,
        body: str,
        *,
        replace: bool = False,
        tags: Iterable[str] = (),
    ) -> None:
        draft = PromptDraft(name=name, body=body, replace=replace, tags=tags)
        now = self._db.now()
        with self._db.connect() as conn:
            if draft.replace:
                existing = conn.execute(
                    "SELECT created_at, body FROM prompts WHERE name = ?",
                    (draft.name,),
                ).fetchone()
                created_at = existing["created_at"] if existing else now
                if existing and existing["body"] != body:
                    self._save_version(conn, draft.name, existing["body"], VersionReason.REPLACE)
                conn.execute(
                    """
                    INSERT INTO prompts (name, body, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        body = excluded.body,
                        updated_at = excluded.updated_at
                    """,
                    (draft.name, draft.body, created_at, now),
                )
                self._apply_tags(conn, draft.name, draft.tags)
                action = UsageAction.REPLACE if existing else UsageAction.ADD
                self._record_usage(conn, action, [draft.name])
                return

            try:
                conn.execute(
                    """
                    INSERT INTO prompts (name, body, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (draft.name, draft.body, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise PromptExistsError(draft.name) from exc
            self._apply_tags(conn, draft.name, draft.tags)
            self._record_usage(conn, UsageAction.ADD, [draft.name])

    def update(self, name: str, body: str) -> None:
        now = self._db.now()
        with self._db.connect() as conn:
            existing = conn.execute(
                "SELECT body FROM prompts WHERE name = ?",
                (name,),
            ).fetchone()
            if existing is None:
                raise PromptNotFoundError(name)
            if existing["body"] != body:
                self._save_version(conn, name, existing["body"], VersionReason.EDIT)
            result = conn.execute(
                "UPDATE prompts SET body = ?, updated_at = ? WHERE name = ?",
                (body, now, name),
            )
            if result.rowcount == 0:
                raise PromptNotFoundError(name)
            self._record_usage(conn, UsageAction.EDIT, [name])

    def get(self, name: str) -> Prompt:
        with self._db.connect() as conn:
            row = conn.execute(
                """
                SELECT name, body, created_at, updated_at
                FROM prompts
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
            if row is None:
                raise PromptNotFoundError(name)
            tags = self._tags_for(conn, name)
        return Prompt(
            name=row["name"],
            body=row["body"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tags=tags,
        )

    def list(self, *, tags: Iterable[str] = (), query: str | None = None) -> list[Prompt]:
        search = PromptSearch(tags=tags, query=query)
        wanted_tags = set(search.tags)
        query_text = search.query.casefold() if search.query else None
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT name, body, created_at, updated_at
                FROM prompts
                ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
            prompts = [
                Prompt(
                    name=row["name"],
                    body=row["body"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    tags=self._tags_for(conn, row["name"]),
                )
                for row in rows
            ]

        if wanted_tags:
            prompts = [
                prompt
                for prompt in prompts
                if wanted_tags.issubset(set(prompt.tags))
            ]
        if query_text:
            prompts = [
                prompt
                for prompt in prompts
                if query_text in prompt.name.casefold()
                or query_text in prompt.body.casefold()
                or any(query_text in tag.casefold() for tag in prompt.tags)
            ]
        return prompts

    def add_tags(self, name: str, tags: Iterable[str]) -> None:
        with self._db.connect() as conn:
            if not self._prompt_exists(conn, name):
                raise PromptNotFoundError(name)
            self._apply_tags(conn, name, tags)
            self._record_usage(conn, UsageAction.TAG, [name], detail="add")

    def remove_tags(self, name: str, tags: Iterable[str]) -> None:
        normalized = self._normalize_tags(tags)
        with self._db.connect() as conn:
            if not self._prompt_exists(conn, name):
                raise PromptNotFoundError(name)
            conn.executemany(
                "DELETE FROM prompt_tags WHERE prompt_name = ? AND tag_name = ?",
                [(name, tag) for tag in normalized],
            )
            conn.execute(
                """
                DELETE FROM tags
                WHERE NOT EXISTS (
                    SELECT 1 FROM prompt_tags WHERE prompt_tags.tag_name = tags.name
                )
                """
            )
            self._record_usage(conn, UsageAction.TAG, [name], detail="remove")

    def tags(self) -> list[TagSummary]:
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT tags.name, COUNT(prompt_tags.prompt_name) AS prompt_count
                FROM tags
                LEFT JOIN prompt_tags ON prompt_tags.tag_name = tags.name
                GROUP BY tags.name
                ORDER BY prompt_count DESC, tags.name COLLATE NOCASE
                """
            ).fetchall()
        return [TagSummary(name=row["name"], prompt_count=row["prompt_count"]) for row in rows]

    def stats(self, name: str | None = None) -> list[PromptStats]:
        params: tuple[str, ...] = (name,) if name else ()
        where = "WHERE prompts.name = ?" if name else ""
        with self._db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    prompts.name AS name,
                    COALESCE(usage.show_count, 0) AS show_count,
                    COALESCE(usage.edit_count, 0) AS edit_count,
                    COALESCE(feedback_counts.feedback_count, 0) AS feedback_count,
                    usage.last_used_at AS last_used_at
                FROM prompts
                LEFT JOIN (
                    SELECT
                        prompt_usage.prompt_name AS prompt_name,
                        SUM(CASE WHEN usage_events.action = 'show' THEN 1 ELSE 0 END) AS show_count,
                        SUM(CASE WHEN usage_events.action = 'edit' THEN 1 ELSE 0 END) AS edit_count,
                        MAX(usage_events.used_at) AS last_used_at
                    FROM prompt_usage
                    JOIN usage_events ON usage_events.id = prompt_usage.event_id
                    GROUP BY prompt_usage.prompt_name
                ) AS usage ON usage.prompt_name = prompts.name
                LEFT JOIN (
                    SELECT prompt_name, COUNT(*) AS feedback_count
                    FROM feedback
                    GROUP BY prompt_name
                ) AS feedback_counts ON feedback_counts.prompt_name = prompts.name
                {where}
                ORDER BY last_used_at DESC, prompts.name COLLATE NOCASE
                """,
                params,
            ).fetchall()
        if name and not rows:
            raise PromptNotFoundError(name)
        return [
            PromptStats(
                name=row["name"],
                show_count=row["show_count"] or 0,
                edit_count=row["edit_count"] or 0,
                feedback_count=row["feedback_count"] or 0,
                last_used_at=row["last_used_at"],
            )
            for row in rows
        ]

    def usage(self, name: str | None = None, *, limit: int = 50) -> list[UsageEvent]:
        params: list[str | int] = []
        where = ""
        if name:
            with self._db.connect() as conn:
                if not self._prompt_exists(conn, name):
                    raise PromptNotFoundError(name)
            where = "WHERE usage_events.id IN (SELECT event_id FROM prompt_usage WHERE prompt_name = ?)"
            params.append(name)
        params.append(limit)

        with self._db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    usage_events.id AS id,
                    usage_events.action AS action,
                    usage_events.used_at AS used_at,
                    usage_events.detail AS detail,
                    GROUP_CONCAT(prompt_usage.prompt_name, ',') AS prompt_names
                FROM usage_events
                LEFT JOIN prompt_usage ON prompt_usage.event_id = usage_events.id
                {where}
                GROUP BY usage_events.id
                ORDER BY usage_events.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            UsageEvent(
                id=row["id"],
                action=row["action"],
                used_at=row["used_at"],
                detail=row["detail"],
                prompt_names=tuple(filter(None, (row["prompt_names"] or "").split(","))),
            )
            for row in rows
        ]

    def versions(self, name: str) -> list[PromptVersion]:
        with self._db.connect() as conn:
            if not self._prompt_exists(conn, name):
                raise PromptNotFoundError(name)
            rows = conn.execute(
                """
                SELECT id, prompt_name, body, created_at, reason
                FROM prompt_versions
                WHERE prompt_name = ?
                ORDER BY id DESC
                """,
                (name,),
            ).fetchall()
        return [
            PromptVersion(
                id=row["id"],
                prompt_name=row["prompt_name"],
                body=row["body"],
                created_at=row["created_at"],
                reason=row["reason"],
            )
            for row in rows
        ]

    def get_version(self, name: str, version_id: int) -> PromptVersion:
        with self._db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, prompt_name, body, created_at, reason
                FROM prompt_versions
                WHERE prompt_name = ? AND id = ?
                """,
                (name, version_id),
            ).fetchone()
        if row is None:
            raise PromptNotFoundError(f"{name} version {version_id}")
        return PromptVersion(
            id=row["id"],
            prompt_name=row["prompt_name"],
            body=row["body"],
            created_at=row["created_at"],
            reason=row["reason"],
        )

    def prune_versions(self, name: str) -> int:
        with self._db.connect() as conn:
            if not self._prompt_exists(conn, name):
                raise PromptNotFoundError(name)
            result = conn.execute("DELETE FROM prompt_versions WHERE prompt_name = ?", (name,))
            self._record_usage(conn, UsageAction.VERSIONS, [name], detail="prune")
            return result.rowcount

    def add_feedback(self, name: str, body: str) -> None:
        with self._db.connect() as conn:
            if not self._prompt_exists(conn, name):
                raise PromptNotFoundError(name)
            conn.execute(
                """
                INSERT INTO feedback (prompt_name, body, created_at)
                VALUES (?, ?, ?)
                """,
                (name, body, self._db.now()),
            )
            self._record_usage(conn, UsageAction.FEEDBACK, [name])

    def feedback(self, name: str) -> list[Feedback]:
        with self._db.connect() as conn:
            if not self._prompt_exists(conn, name):
                raise PromptNotFoundError(name)
            rows = conn.execute(
                """
                SELECT id, prompt_name, body, created_at
                FROM feedback
                WHERE prompt_name = ?
                ORDER BY id DESC
                """,
                (name,),
            ).fetchall()
        return [
            Feedback(
                id=row["id"],
                prompt_name=row["prompt_name"],
                body=row["body"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def remove(self, name: str) -> None:
        with self._db.connect() as conn:
            if not self._prompt_exists(conn, name):
                raise PromptNotFoundError(name)
            conn.execute("DELETE FROM prompt_tags WHERE prompt_name = ?", (name,))
            conn.execute("DELETE FROM prompt_usage WHERE prompt_name = ?", (name,))
            conn.execute("DELETE FROM prompt_versions WHERE prompt_name = ?", (name,))
            conn.execute("DELETE FROM feedback WHERE prompt_name = ?", (name,))
            result = conn.execute("DELETE FROM prompts WHERE name = ?", (name,))
            if result.rowcount == 0:
                raise PromptNotFoundError(name)
            conn.execute(
                """
                DELETE FROM tags
                WHERE NOT EXISTS (
                    SELECT 1 FROM prompt_tags WHERE prompt_tags.tag_name = tags.name
                )
                """
            )
