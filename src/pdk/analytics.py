from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .database import SQLiteDatabase
from .file_index import FileIndex
from .project import ProjectResolver
from .tokens import count_tokens


SUBCOMMAND_ATTRS = (
    "file_command",
    "tag_command",
    "project_command",
    "privacy_command",
    "note_command",
    "session_command",
    "security_command",
)
DISABLE_ANALYTICS_ENV = "PDK_DISABLE_ANALYTICS"


@dataclass(frozen=True)
class CommandUsageRow:
    command: str
    variant: str
    total_count: int
    ok_count: int
    error_count: int
    last_used_at: str | None


@dataclass(frozen=True)
class MemoryUsageRow:
    component: str
    items: int
    bytes: int
    tokens: int | None = None
    detail: str = ""


def _text_bytes(value: str | None) -> int:
    return len((value or "").encode("utf-8"))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
    return row is not None


def command_variant(args: argparse.Namespace) -> tuple[str, str]:
    command = str(getattr(args, "command", "") or "unknown")
    parts = [command]
    if command == "stats":
        target = getattr(args, "stats_target", None)
        if target in {"use", "mem"}:
            parts.append(target)
    for attr in SUBCOMMAND_ATTRS:
        value = getattr(args, attr, None)
        if value:
            parts.append(str(value))
    return command, " ".join(parts)


def command_log_database_path(args: argparse.Namespace) -> Path:
    try:
        return ProjectResolver().resolve(args.scope).database_path
    except Exception:
        return SQLiteDatabase.default_path()


def analytics_disabled() -> bool:
    return os.environ.get(DISABLE_ANALYTICS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


class AnalyticsStore:
    def __init__(self, path: Path | None = None) -> None:
        self._db = SQLiteDatabase(path)
        self.path = self._db.path

    def record_command(self, args: argparse.Namespace, *, status: str, detail: str | None = None) -> None:
        if analytics_disabled():
            return
        command, variant = command_variant(args)
        with self._db.connect() as conn:
            conn.execute(
                """
                INSERT INTO command_usage_events (command, variant, status, used_at, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (command, variant, status, self._db.now(), detail),
            )

    def command_usage(self, *, limit: int | None = None) -> list[CommandUsageRow]:
        limit_sql = "" if limit is None else "LIMIT ?"
        params: tuple[int, ...] = () if limit is None else (limit,)
        with self._db.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    command,
                    variant,
                    COUNT(*) AS total_count,
                    SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS ok_count,
                    SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END) AS error_count,
                    MAX(used_at) AS last_used_at
                FROM command_usage_events
                GROUP BY command, variant
                ORDER BY total_count DESC, error_count DESC, last_used_at DESC, variant COLLATE NOCASE
                {limit_sql}
                """,
                params,
            ).fetchall()
        return [
            CommandUsageRow(
                command=row["command"],
                variant=row["variant"],
                total_count=int(row["total_count"] or 0),
                ok_count=int(row["ok_count"] or 0),
                error_count=int(row["error_count"] or 0),
                last_used_at=row["last_used_at"],
            )
            for row in rows
        ]

    def memory_usage(self, *, index_path: Path | None = None) -> list[MemoryUsageRow]:
        rows: list[MemoryUsageRow] = []
        with self._db.connect() as conn:
            rows.extend(
                [
                    self._text_table(conn, "prompts", "body", "prompts"),
                    self._text_table(conn, "prompt_versions", "body", "prompt_versions"),
                    self._text_table(conn, "feedback", "body", "feedback"),
                    self._text_table(conn, "notes", "body", "notes"),
                    self._text_table(conn, "note_versions", "body", "note_versions"),
                    self._usage_table(conn),
                    self._command_table(conn),
                ]
            )
        if self.path.exists():
            rows.append(MemoryUsageRow("prompt_db_file", 1, self.path.stat().st_size, detail=str(self.path)))

        resolved_index_path = index_path or FileIndex.default_path()
        if not resolved_index_path.exists():
            rows.extend(
                [
                    MemoryUsageRow("indexed_files", 0, 0, 0),
                    MemoryUsageRow("index_chunks", 0, 0, 0),
                    MemoryUsageRow("chunk_summaries", 0, 0),
                    MemoryUsageRow("file_summaries", 0, 0),
                    MemoryUsageRow("embeddings", 0, 0),
                ]
            )
            return rows

        file_index = FileIndex(resolved_index_path)
        with file_index.connect() as conn:
            rows.extend(
                [
                    self._index_files_table(conn),
                    self._index_text_table(conn, "file_chunks", "text", "index_chunks", token_column="token_count"),
                    self._index_text_table(conn, "file_chunks", "summary", "chunk_summaries"),
                    self._index_text_table(conn, "file_summaries", "summary", "file_summaries"),
                    self._embedding_table(conn),
                ]
            )
        if file_index.path.exists():
            rows.append(MemoryUsageRow("index_db_file", 1, file_index.path.stat().st_size, detail=str(file_index.path)))
        return rows

    def _text_table(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        component: str,
    ) -> MemoryUsageRow:
        if not _table_exists(conn, table):
            return MemoryUsageRow(component, 0, 0, 0)
        values = [row[column] or "" for row in conn.execute(f"SELECT {column} FROM {table}").fetchall()]
        return MemoryUsageRow(
            component,
            len(values),
            sum(_text_bytes(value) for value in values),
            sum(count_tokens(value) for value in values),
        )

    def _usage_table(self, conn: sqlite3.Connection) -> MemoryUsageRow:
        if not _table_exists(conn, "usage_events"):
            return MemoryUsageRow("prompt_usage_log", 0, 0)
        rows = conn.execute("SELECT action, detail FROM usage_events").fetchall()
        return MemoryUsageRow(
            "prompt_usage_log",
            len(rows),
            sum(_text_bytes(row["action"]) + _text_bytes(row["detail"]) for row in rows),
        )

    def _command_table(self, conn: sqlite3.Connection) -> MemoryUsageRow:
        if not _table_exists(conn, "command_usage_events"):
            return MemoryUsageRow("command_usage_log", 0, 0)
        rows = conn.execute("SELECT command, variant, status, detail FROM command_usage_events").fetchall()
        return MemoryUsageRow(
            "command_usage_log",
            len(rows),
            sum(
                _text_bytes(row["command"])
                + _text_bytes(row["variant"])
                + _text_bytes(row["status"])
                + _text_bytes(row["detail"])
                for row in rows
            ),
        )

    def _index_files_table(self, conn: sqlite3.Connection) -> MemoryUsageRow:
        if not _table_exists(conn, "files"):
            return MemoryUsageRow("indexed_files", 0, 0, 0)
        row = conn.execute(
            """
            SELECT COUNT(*) AS items, COALESCE(SUM(size_bytes), 0) AS bytes, COALESCE(SUM(token_count), 0) AS tokens
            FROM files
            """
        ).fetchone()
        return MemoryUsageRow("indexed_files", int(row["items"]), int(row["bytes"]), int(row["tokens"]))

    def _index_text_table(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        component: str,
        *,
        token_column: str | None = None,
    ) -> MemoryUsageRow:
        if not _table_exists(conn, table):
            return MemoryUsageRow(component, 0, 0, 0 if token_column else None)
        values = [row[column] or "" for row in conn.execute(f"SELECT {column} FROM {table}").fetchall()]
        tokens = None
        if token_column is not None:
            row = conn.execute(f"SELECT COALESCE(SUM({token_column}), 0) AS tokens FROM {table}").fetchone()
            tokens = int(row["tokens"])
        elif values:
            tokens = sum(count_tokens(value) for value in values)
        return MemoryUsageRow(component, len(values), sum(_text_bytes(value) for value in values), tokens)

    def _embedding_table(self, conn: sqlite3.Connection) -> MemoryUsageRow:
        if not _table_exists(conn, "embeddings"):
            return MemoryUsageRow("embeddings", 0, 0)
        row = conn.execute(
            "SELECT COUNT(*) AS items, COALESCE(SUM(LENGTH(vector_blob)), 0) AS bytes FROM embeddings"
        ).fetchone()
        return MemoryUsageRow("embeddings", int(row["items"]), int(row["bytes"]))
