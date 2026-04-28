from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .database import SQLiteDatabase, database_path, default_home
from .models import (
    Feedback,
    Note,
    NoteDraft,
    NoteVersion,
    Prompt,
    PromptDraft,
    PromptSearch,
    PromptStats,
    PromptVersion,
    Project,
    ProjectDraft,
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


class ProjectExistsError(Exception):
    pass


class NamedProjectNotFoundError(Exception):
    pass


class NoteNotFoundError(Exception):
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

    def create_project(self, name: str, description: str = "") -> Project:
        draft = ProjectDraft(name=name, description=description)
        now = self._db.now()
        with self._db.connect() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO projects (name, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (draft.name, draft.description, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ProjectExistsError(draft.name) from exc
            row = conn.execute(
                """
                SELECT id, name, description, created_at, updated_at
                FROM projects
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return self._project_from_row(row)

    def projects(self) -> list[Project]:
        with self._db.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, description, created_at, updated_at
                FROM projects
                ORDER BY name COLLATE NOCASE
                """
            ).fetchall()
        return [self._project_from_row(row) for row in rows]

    def get_project(self, name: str) -> Project:
        with self._db.connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, description, created_at, updated_at
                FROM projects
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
        if row is None:
            raise NamedProjectNotFoundError(name)
        return self._project_from_row(row)

    def project_id(self, name: str) -> int:
        with self._db.connect() as conn:
            return self._project_id_for(conn, name)

    def active_project(self) -> Project | None:
        with self._db.connect() as conn:
            row = conn.execute(
                """
                SELECT projects.id, projects.name, projects.description, projects.created_at, projects.updated_at
                FROM settings
                JOIN projects ON projects.id = CAST(settings.value AS INTEGER)
                WHERE settings.key = 'active_project_id'
                """
            ).fetchone()
        return self._project_from_row(row) if row else None

    def use_project(self, name: str) -> Project:
        now = self._db.now()
        with self._db.connect() as conn:
            project_id = self._project_id_for(conn, name)
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES ('active_project_id', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (str(project_id), now),
            )
            row = conn.execute(
                """
                SELECT id, name, description, created_at, updated_at
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            ).fetchone()
        return self._project_from_row(row)

    def update_project(
        self,
        name: str,
        *,
        new_name: str | None = None,
        description: str | None = None,
    ) -> Project:
        now = self._db.now()
        with self._db.connect() as conn:
            existing = conn.execute(
                """
                SELECT id, name, description, created_at, updated_at
                FROM projects
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
            if existing is None:
                raise NamedProjectNotFoundError(name)

            target = ProjectDraft(
                name=new_name if new_name is not None else existing["name"],
                description=description if description is not None else existing["description"],
            )
            if target.name == existing["name"] and target.description == existing["description"]:
                return self._project_from_row(existing)

            try:
                conn.execute(
                    """
                    UPDATE projects
                    SET name = ?, description = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (target.name, target.description, now, existing["id"]),
                )
            except sqlite3.IntegrityError as exc:
                raise ProjectExistsError(target.name) from exc
            row = conn.execute(
                """
                SELECT id, name, description, created_at, updated_at
                FROM projects
                WHERE id = ?
                """,
                (existing["id"],),
            ).fetchone()
        return self._project_from_row(row)

    def rename_project(self, old_name: str, new_name: str) -> Project:
        return self.update_project(old_name, new_name=new_name)

    def describe_project(self, name: str, description: str) -> Project:
        return self.update_project(name, description=description)

    def clear_active_project(self) -> None:
        with self._db.connect() as conn:
            conn.execute("DELETE FROM settings WHERE key = 'active_project_id'")

    def assign_project(self, project_name: str, prompt_names: Iterable[str]) -> None:
        names = list(prompt_names)
        now = self._db.now()
        with self._db.connect() as conn:
            project_id = self._project_id_for(conn, project_name)
            for name in names:
                if not self._prompt_exists(conn, name):
                    raise PromptNotFoundError(name)
            conn.executemany(
                "UPDATE prompts SET project_id = ?, updated_at = ? WHERE name = ?",
                [(project_id, now, name) for name in names],
            )

    def unassign_project(self, prompt_names: Iterable[str]) -> None:
        names = list(prompt_names)
        now = self._db.now()
        with self._db.connect() as conn:
            for name in names:
                if not self._prompt_exists(conn, name):
                    raise PromptNotFoundError(name)
            conn.executemany(
                "UPDATE prompts SET project_id = NULL, updated_at = ? WHERE name = ?",
                [(now, name) for name in names],
            )

    def add(
        self,
        name: str,
        body: str,
        *,
        replace: bool = False,
        tags: Iterable[str] = (),
        project_id: int | None = None,
    ) -> None:
        draft = PromptDraft(name=name, body=body, replace=replace, tags=tags, project_id=project_id)
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
                    INSERT INTO prompts (name, body, created_at, updated_at, project_id)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        body = excluded.body,
                        updated_at = excluded.updated_at,
                        project_id = excluded.project_id
                    """,
                    (draft.name, draft.body, created_at, now, draft.project_id),
                )
                self._apply_tags(conn, draft.name, draft.tags)
                action = UsageAction.REPLACE if existing else UsageAction.ADD
                self._record_usage(conn, action, [draft.name])
                return

            try:
                conn.execute(
                    """
                    INSERT INTO prompts (name, body, created_at, updated_at, project_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (draft.name, draft.body, now, now, draft.project_id),
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
                SELECT prompts.name, prompts.body, prompts.created_at, prompts.updated_at,
                    prompts.project_id, projects.name AS project_name
                FROM prompts
                LEFT JOIN projects ON projects.id = prompts.project_id
                WHERE prompts.name = ?
                """,
                (name,),
            ).fetchone()
            if row is None:
                raise PromptNotFoundError(name)
            return self._prompt_from_row(conn, row)

    def list(
        self,
        *,
        tags: Iterable[str] = (),
        query: str | None = None,
        project_id: int | None = None,
        project_filter: bool = False,
    ) -> list[Prompt]:
        search = PromptSearch(tags=tags, query=query)
        wanted_tags = set(search.tags)
        query_text = search.query.casefold() if search.query else None
        where = "WHERE prompts.project_id IS ?" if project_filter else ""
        params = (project_id,) if project_filter else ()
        with self._db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT prompts.name, prompts.body, prompts.created_at, prompts.updated_at,
                    prompts.project_id, projects.name AS project_name
                FROM prompts
                LEFT JOIN projects ON projects.id = prompts.project_id
                {where}
                ORDER BY prompts.name COLLATE NOCASE
                """,
                params,
            ).fetchall()
            prompts = [self._prompt_from_row(conn, row) for row in rows]

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

    def tags(
        self,
        *,
        project_id: int | None = None,
        project_filter: bool = False,
    ) -> list[TagSummary]:
        project_join = "JOIN prompts ON prompts.name = prompt_tags.prompt_name" if project_filter else ""
        project_where = "WHERE prompts.project_id IS ?" if project_filter else ""
        params = (project_id,) if project_filter else ()
        with self._db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT tags.name, COUNT(prompt_tags.prompt_name) AS prompt_count
                FROM tags
                LEFT JOIN prompt_tags ON prompt_tags.tag_name = tags.name
                {project_join}
                {project_where}
                GROUP BY tags.name
                ORDER BY prompt_count DESC, tags.name COLLATE NOCASE
                """,
                params,
            ).fetchall()
        return [TagSummary(name=row["name"], prompt_count=row["prompt_count"]) for row in rows]

    def stats(
        self,
        name: str | None = None,
        *,
        project_id: int | None = None,
        project_filter: bool = False,
    ) -> list[PromptStats]:
        clauses = []
        params: list[str | int | None] = []
        if name:
            clauses.append("prompts.name = ?")
            params.append(name)
        if project_filter:
            clauses.append("prompts.project_id IS ?")
            params.append(project_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
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
                        MAX(CASE WHEN usage_events.action = 'show' THEN usage_events.used_at END) AS last_used_at
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

    def usage(
        self,
        name: str | None = None,
        *,
        limit: int = 50,
        project_id: int | None = None,
        project_filter: bool = False,
    ) -> list[UsageEvent]:
        params: list[str | int | None] = []
        clauses = []
        if name:
            with self._db.connect() as conn:
                if not self._prompt_exists(conn, name):
                    raise PromptNotFoundError(name)
            clauses.append("usage_events.id IN (SELECT event_id FROM prompt_usage WHERE prompt_name = ?)")
            params.append(name)
        if project_filter:
            clauses.append(
                """
                usage_events.id IN (
                    SELECT prompt_usage.event_id
                    FROM prompt_usage
                    JOIN prompts ON prompts.name = prompt_usage.prompt_name
                    WHERE prompts.project_id IS ?
                )
                """
            )
            params.append(project_id)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
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

    def add_note(self, body: str, *, title: str | None = None, project_id: int | None = None) -> Note:
        draft = NoteDraft(body=body, title=title, project_id=project_id)
        now = self._db.now()
        with self._db.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO notes (project_id, title, body, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (draft.project_id, draft.title, draft.body, now, now),
            )
            row = conn.execute(
                """
                SELECT notes.id, notes.project_id, projects.name AS project_name,
                    notes.title, notes.body, notes.created_at, notes.updated_at
                FROM notes
                LEFT JOIN projects ON projects.id = notes.project_id
                WHERE notes.id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        return self._note_from_row(row)

    def get_note(self, note_id: int) -> Note:
        with self._db.connect() as conn:
            row = conn.execute(
                """
                SELECT notes.id, notes.project_id, projects.name AS project_name,
                    notes.title, notes.body, notes.created_at, notes.updated_at
                FROM notes
                LEFT JOIN projects ON projects.id = notes.project_id
                WHERE notes.id = ?
                """,
                (note_id,),
            ).fetchone()
        if row is None:
            raise NoteNotFoundError(str(note_id))
        return self._note_from_row(row)

    def notes(
        self,
        *,
        project_id: int | None = None,
        project_filter: bool = False,
    ) -> list[Note]:
        where = "WHERE notes.project_id IS ?" if project_filter else ""
        params = (project_id,) if project_filter else ()
        with self._db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT notes.id, notes.project_id, projects.name AS project_name,
                    notes.title, notes.body, notes.created_at, notes.updated_at
                FROM notes
                LEFT JOIN projects ON projects.id = notes.project_id
                {where}
                ORDER BY notes.created_at, notes.id
                """,
                params,
            ).fetchall()
        return [self._note_from_row(row) for row in rows]

    def update_note(self, note_id: int, body: str, *, title: str | None = None) -> None:
        now = self._db.now()
        with self._db.connect() as conn:
            existing = conn.execute(
                "SELECT title, body FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
            if existing is None:
                raise NoteNotFoundError(str(note_id))
            if existing["body"] == body and existing["title"] == title:
                return
            conn.execute(
                """
                INSERT INTO note_versions (note_id, title, body, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (note_id, existing["title"], existing["body"], now),
            )
            conn.execute(
                """
                UPDATE notes
                SET title = ?, body = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, body, now, note_id),
            )

    def note_versions(self, note_id: int) -> list[NoteVersion]:
        with self._db.connect() as conn:
            if conn.execute("SELECT 1 FROM notes WHERE id = ?", (note_id,)).fetchone() is None:
                raise NoteNotFoundError(str(note_id))
            rows = conn.execute(
                """
                SELECT id, note_id, title, body, created_at
                FROM note_versions
                WHERE note_id = ?
                ORDER BY id DESC
                """,
                (note_id,),
            ).fetchall()
        return [
            NoteVersion(
                id=row["id"],
                note_id=row["note_id"],
                title=row["title"],
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
