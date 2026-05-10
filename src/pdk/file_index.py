from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import sqlite3
from pathlib import Path
from typing import Iterator

from .database import SQLiteDatabase
from .privacy import PrivateFinding


INDEX_DB = "index.sqlite3"
SCHEMA_VERSION = 1
EXTRACTOR_VERSION = "pdk.sources.v1"


@dataclass(frozen=True)
class FileRecord:
    id: int
    path: str
    kind: str
    size_bytes: int
    mtime: float
    sha256: str
    indexed_at: str
    status: str
    token_count: int
    line_count: int
    char_count: int
    finding_count: int
    summary: str | None


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    token_count: int


class FileIndex:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or self.default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @staticmethod
    def default_path() -> Path:
        return SQLiteDatabase.default_home() / INDEX_DB

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
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    uri TEXT,
                    kind TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    sha256 TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    extractor TEXT NOT NULL,
                    extractor_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    token_count INTEGER NOT NULL DEFAULT 0,
                    line_count INTEGER NOT NULL DEFAULT 0,
                    char_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    page_start INTEGER,
                    page_end INTEGER,
                    char_start INTEGER NOT NULL,
                    char_end INTEGER NOT NULL,
                    token_count INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    redacted_text TEXT,
                    summary TEXT,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    UNIQUE (file_id, chunk_index)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS privacy_findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    chunk_id INTEGER,
                    entity TEXT NOT NULL,
                    label TEXT NOT NULL,
                    start INTEGER NOT NULL,
                    end INTEGER NOT NULL,
                    score REAL NOT NULL,
                    detector TEXT NOT NULL,
                    replacement TEXT,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    FOREIGN KEY (chunk_id) REFERENCES file_chunks(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    entity_type TEXT NOT NULL,
                    value_hash TEXT NOT NULL,
                    display_value TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                    UNIQUE (file_id, entity_type, value_hash)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_id INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    vector_blob BLOB NOT NULL,
                    FOREIGN KEY (chunk_id) REFERENCES file_chunks(id) ON DELETE CASCADE,
                    UNIQUE (chunk_id, model)
                )
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def upsert_file(
        self,
        *,
        path: Path,
        kind: str,
        sha256: str,
        token_count: int,
        line_count: int,
        char_count: int,
        status: str = "indexed",
        error: str | None = None,
    ) -> int:
        stat = path.stat()
        now = self.now()
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM files WHERE path = ?", (str(path),)).fetchone()
            if row is None:
                cursor = conn.execute(
                    """
                    INSERT INTO files (
                        path, uri, kind, size_bytes, mtime, sha256, discovered_at,
                        indexed_at, extractor, extractor_version, status, error,
                        token_count, line_count, char_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(path),
                        path.as_uri() if path.is_absolute() else None,
                        kind,
                        stat.st_size,
                        stat.st_mtime,
                        sha256,
                        now,
                        now,
                        "pdk.sources",
                        EXTRACTOR_VERSION,
                        status,
                        error,
                        token_count,
                        line_count,
                        char_count,
                    ),
                )
                return int(cursor.lastrowid)
            file_id = int(row["id"])
            conn.execute(
                """
                UPDATE files
                SET uri = ?, kind = ?, size_bytes = ?, mtime = ?, sha256 = ?,
                    indexed_at = ?, extractor = ?, extractor_version = ?,
                    status = ?, error = ?, token_count = ?, line_count = ?, char_count = ?
                WHERE id = ?
                """,
                (
                    path.as_uri() if path.is_absolute() else None,
                    kind,
                    stat.st_size,
                    stat.st_mtime,
                    sha256,
                    now,
                    "pdk.sources",
                    EXTRACTOR_VERSION,
                    status,
                    error,
                    token_count,
                    line_count,
                    char_count,
                    file_id,
                ),
            )
            conn.execute("DELETE FROM file_chunks WHERE file_id = ?", (file_id,))
            conn.execute("DELETE FROM privacy_findings WHERE file_id = ?", (file_id,))
            conn.execute("DELETE FROM file_entities WHERE file_id = ?", (file_id,))
            return file_id

    def add_chunks(self, file_id: int, chunks: list[ChunkDraft]) -> dict[int, int]:
        ids: dict[int, int] = {}
        with self.connect() as conn:
            for chunk in chunks:
                cursor = conn.execute(
                    """
                    INSERT INTO file_chunks (
                        file_id, chunk_index, char_start, char_end, token_count, text
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_id,
                        chunk.chunk_index,
                        chunk.char_start,
                        chunk.char_end,
                        chunk.token_count,
                        chunk.text,
                    ),
                )
                ids[chunk.chunk_index] = int(cursor.lastrowid)
        return ids

    def add_findings(
        self,
        file_id: int,
        findings_by_chunk: list[tuple[int, PrivateFinding]],
        chunk_ids: dict[int, int],
    ) -> None:
        with self.connect() as conn:
            for chunk_index, finding in findings_by_chunk:
                conn.execute(
                    """
                    INSERT INTO privacy_findings (
                        file_id, chunk_id, entity, label, start, end, score, detector
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_id,
                        chunk_ids.get(chunk_index),
                        finding.name,
                        finding.label,
                        finding.start,
                        finding.end,
                        finding.score,
                        finding.detector,
                    ),
                )

    def add_entities(self, file_id: int, findings: list[PrivateFinding]) -> None:
        counts = Counter((finding.name, finding.text, finding.detector) for finding in findings)
        with self.connect() as conn:
            for (entity_type, value, detector), count in counts.items():
                value_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()
                display_value = value if len(value) <= 80 else value[:77] + "..."
                conn.execute(
                    """
                    INSERT OR REPLACE INTO file_entities (
                        file_id, entity_type, value_hash, display_value, count, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (file_id, entity_type, value_hash, display_value, count, detector),
                )

    def add_summary(
        self,
        file_id: int,
        *,
        level: str,
        model: str,
        prompt_version: str,
        summary: str,
        tags_json: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO file_summaries (
                    file_id, level, model, prompt_version, summary, tags_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (file_id, level, model, prompt_version, summary, tags_json, self.now()),
            )

    def files(self) -> list[FileRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    files.*,
                    COUNT(privacy_findings.id) AS finding_count,
                    (
                        SELECT summary
                        FROM file_summaries
                        WHERE file_summaries.file_id = files.id
                        ORDER BY id DESC
                        LIMIT 1
                    ) AS summary
                FROM files
                LEFT JOIN privacy_findings ON privacy_findings.file_id = files.id
                GROUP BY files.id
                ORDER BY files.indexed_at DESC, files.path
                """
            ).fetchall()
        return [
            FileRecord(
                id=int(row["id"]),
                path=row["path"],
                kind=row["kind"],
                size_bytes=int(row["size_bytes"]),
                mtime=float(row["mtime"]),
                sha256=row["sha256"],
                indexed_at=row["indexed_at"],
                status=row["status"],
                token_count=int(row["token_count"]),
                line_count=int(row["line_count"]),
                char_count=int(row["char_count"]),
                finding_count=int(row["finding_count"]),
                summary=row["summary"],
            )
            for row in rows
        ]

    def get_file(self, value: str) -> FileRecord:
        query = "SELECT * FROM files WHERE id = ?" if value.isdecimal() else "SELECT * FROM files WHERE path = ?"
        param: int | str = int(value) if value.isdecimal() else value
        with self.connect() as conn:
            row = conn.execute(query, (param,)).fetchone()
        if row is None:
            raise KeyError(value)
        finding_count = self.finding_count(int(row["id"]))
        summary = self.latest_summary(int(row["id"]))
        return FileRecord(
            id=int(row["id"]),
            path=row["path"],
            kind=row["kind"],
            size_bytes=int(row["size_bytes"]),
            mtime=float(row["mtime"]),
            sha256=row["sha256"],
            indexed_at=row["indexed_at"],
            status=row["status"],
            token_count=int(row["token_count"]),
            line_count=int(row["line_count"]),
            char_count=int(row["char_count"]),
            finding_count=finding_count,
            summary=summary,
        )

    def finding_count(self, file_id: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM privacy_findings WHERE file_id = ?",
                (file_id,),
            ).fetchone()
        return int(row["count"])

    def latest_summary(self, file_id: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT summary FROM file_summaries
                WHERE file_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (file_id,),
            ).fetchone()
        return row["summary"] if row else None

    def entities(self, value: str) -> list[sqlite3.Row]:
        file = self.get_file(value)
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT entity_type, display_value, count, source
                FROM file_entities
                WHERE file_id = ?
                ORDER BY count DESC, entity_type, display_value
                """,
                (file.id,),
            ).fetchall()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
