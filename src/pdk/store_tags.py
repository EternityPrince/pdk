from __future__ import annotations

from typing import Iterable

from .models import PromptStats, TagSummary, UsageAction
from .store_base import PromptNotFoundError


class TagStatsStoreMixin:
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

    # Usage, versions, and feedback
