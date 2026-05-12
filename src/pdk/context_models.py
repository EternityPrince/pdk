from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ContextModule:
    name: str
    description: str | None = None
    dirs: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextOptions:
    project_id: int | None = None
    project_filter: bool = False
    project_name: str | None = None
    includes: frozenset[str] = frozenset({"prompts", "notes", "comments"})
    since: str | None = None
    redact: bool = False
    privacy_profile: str | None = None
    privacy_model: bool = False
    privacy_model_name: str | None = None
    privacy_model_threshold: float | None = None
    budget: int | None = None
    database: str = ""
    file_targets: tuple[str, ...] = ()
    dir_targets: tuple[str, ...] = ()
    file_detail: str = "summary"
    file_include_patterns: tuple[str, ...] = ()
    file_exclude_patterns: tuple[str, ...] = ()
    ignore_root: Path | None = None
    modules: tuple[ContextModule, ...] = ()
    compact: bool = False


@dataclass(frozen=True)
class ContextComment:
    id: int
    prompt_name: str
    body: str
    created_at: str


@dataclass(frozen=True)
class ContextPrompt:
    name: str
    body: str
    created_at: str
    updated_at: str
    project_name: str | None = None
    tags: tuple[str, ...] = ()
    comments: tuple[ContextComment, ...] = ()
    versions: tuple[Any, ...] = ()


@dataclass(frozen=True)
class ContextNote:
    id: int
    title: str | None
    body: str
    created_at: str
    updated_at: str
    project_name: str | None = None
    versions: tuple[Any, ...] = ()


@dataclass(frozen=True)
class ContextFile:
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
    detail: str = "summary"
    summary: str | None = None
    text: str | None = None
    module_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextDocument:
    options: ContextOptions
    modules: tuple[ContextModule, ...] = ()
    prompts: tuple[ContextPrompt, ...] = ()
    notes: tuple[ContextNote, ...] = ()
    usage: tuple[Any, ...] = ()
    files: tuple[ContextFile, ...] = ()
    index: dict[str, int] = field(default_factory=dict)
