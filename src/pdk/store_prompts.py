from __future__ import annotations

import sqlite3
from typing import Iterable

from .models import Prompt, PromptDraft, PromptSearch, UsageAction, VersionReason
from .store_base import PromptExistsError, PromptNotFoundError


class PromptStoreMixin:
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

    def import_prompt(
        self,
        name: str,
        body: str,
        *,
        tags: Iterable[str] = (),
        project_id: int | None = None,
        created_at: str,
        updated_at: str,
        replace: bool = False,
    ) -> None:
        draft = PromptDraft(name=name, body=body, replace=replace, tags=tags, project_id=project_id)
        with self._db.connect() as conn:
            exists = self._prompt_exists(conn, draft.name)
            if exists and not draft.replace:
                raise PromptExistsError(draft.name)
            if exists:
                conn.execute(
                    """
                    UPDATE prompts
                    SET body = ?, updated_at = ?, project_id = ?
                    WHERE name = ?
                    """,
                    (draft.body, updated_at, draft.project_id, draft.name),
                )
                conn.execute("DELETE FROM prompt_tags WHERE prompt_name = ?", (draft.name,))
            else:
                conn.execute(
                    """
                    INSERT INTO prompts (name, body, created_at, updated_at, project_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (draft.name, draft.body, created_at, updated_at, draft.project_id),
                )
            self._apply_tags(conn, draft.name, draft.tags)

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

    def rename_prompt(self, old_name: str, new_name: str) -> None:
        draft = PromptDraft(name=new_name, body="")
        now = self._db.now()
        with self._db.connect() as conn:
            row = conn.execute(
                """
                SELECT body, created_at, project_id
                FROM prompts
                WHERE name = ?
                """,
                (old_name,),
            ).fetchone()
            if row is None:
                raise PromptNotFoundError(old_name)
            if self._prompt_exists(conn, draft.name):
                raise PromptExistsError(draft.name)
            conn.execute(
                """
                INSERT INTO prompts (name, body, created_at, updated_at, project_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (draft.name, row["body"], row["created_at"], now, row["project_id"]),
            )
            conn.execute("UPDATE prompt_tags SET prompt_name = ? WHERE prompt_name = ?", (draft.name, old_name))
            conn.execute("UPDATE prompt_usage SET prompt_name = ? WHERE prompt_name = ?", (draft.name, old_name))
            conn.execute("UPDATE prompt_versions SET prompt_name = ? WHERE prompt_name = ?", (draft.name, old_name))
            conn.execute("UPDATE feedback SET prompt_name = ? WHERE prompt_name = ?", (draft.name, old_name))
            conn.execute("DELETE FROM prompts WHERE name = ?", (old_name,))
            self._record_usage(conn, UsageAction.RENAME, [draft.name], detail=old_name)

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

    # Tags and prompt statistics

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
            prompts = [prompt for prompt in prompts if wanted_tags.issubset(set(prompt.tags))]
        if query_text:
            prompts = [
                prompt
                for prompt in prompts
                if query_text in prompt.name.casefold()
                or query_text in prompt.body.casefold()
                or any(query_text in tag.casefold() for tag in prompt.tags)
            ]
        return prompts

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
