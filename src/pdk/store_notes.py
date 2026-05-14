from __future__ import annotations

from .models import Note, NoteDraft, NoteVersion
from .store_base import NoteNotFoundError


class NoteStoreMixin:
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

    def import_note_version(
        self,
        note_id: int,
        body: str,
        *,
        title: str | None,
        created_at: str,
    ) -> None:
        with self._db.connect() as conn:
            if conn.execute("SELECT 1 FROM notes WHERE id = ?", (note_id,)).fetchone() is None:
                raise NoteNotFoundError(str(note_id))
            conn.execute(
                """
                INSERT INTO note_versions (note_id, title, body, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (note_id, title, body, created_at),
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

    # Destructive prompt operations

