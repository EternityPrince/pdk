from __future__ import annotations

from .models import Feedback, PromptVersion, UsageAction, UsageEvent, VersionReason
from .store_base import PromptNotFoundError


class HistoryStoreMixin:
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

    def import_feedback(self, name: str, body: str, created_at: str) -> None:
        with self._db.connect() as conn:
            if not self._prompt_exists(conn, name):
                raise PromptNotFoundError(name)
            conn.execute(
                """
                INSERT INTO feedback (prompt_name, body, created_at)
                VALUES (?, ?, ?)
                """,
                (name, body, created_at),
            )

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

    def import_prompt_version(
        self,
        name: str,
        body: str,
        reason: VersionReason,
        created_at: str,
    ) -> None:
        with self._db.connect() as conn:
            if not self._prompt_exists(conn, name):
                raise PromptNotFoundError(name)
            conn.execute(
                """
                INSERT INTO prompt_versions (prompt_name, body, created_at, reason)
                VALUES (?, ?, ?, ?)
                """,
                (name, body, created_at, reason.value),
            )

    # Notes
