from __future__ import annotations

import sqlite3
from typing import Iterable

from .models import Project, ProjectDraft, UsageAction
from .store_base import NamedProjectNotFoundError, ProjectExistsError, PromptNotFoundError


class ProjectStoreMixin:
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

    def move_prompts(self, prompt_names: Iterable[str], project_name: str | None) -> None:
        names = list(prompt_names)
        now = self._db.now()
        with self._db.connect() as conn:
            project_id = self._project_id_for(conn, project_name) if project_name is not None else None
            for name in names:
                if not self._prompt_exists(conn, name):
                    raise PromptNotFoundError(name)
            conn.executemany(
                "UPDATE prompts SET project_id = ?, updated_at = ? WHERE name = ?",
                [(project_id, now, name) for name in names],
            )
            for name in names:
                self._record_usage(conn, UsageAction.MOVE, [name], detail=project_name or "unbound")

    # Prompt operations

