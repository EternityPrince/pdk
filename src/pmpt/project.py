from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .database import SQLiteDatabase

PROJECT_DIR = ".pmpt"
PROJECT_DB = "prompts.sqlite3"

ScopeMode = Literal["auto", "global", "project"]


class ProjectNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class StoreContext:
    scope: Literal["global", "project"]
    database_path: Path
    project_root: Path | None = None

    @property
    def label(self) -> str:
        if self.scope == "project" and self.project_root is not None:
            return f"project:{self.project_root}"
        return "global"


class ProjectResolver:
    def __init__(self, cwd: Path | None = None) -> None:
        self._cwd = (cwd or Path.cwd()).resolve()

    def initialize(self, path: Path | None = None) -> StoreContext:
        root = (path or self._cwd).expanduser().resolve()
        project_dir = root / PROJECT_DIR
        project_dir.mkdir(parents=True, exist_ok=True)
        gitignore = project_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(f"{PROJECT_DB}\n", encoding="utf-8")
        db_path = project_dir / PROJECT_DB
        SQLiteDatabase(db_path)
        return StoreContext(scope="project", database_path=db_path, project_root=root)

    def resolve(self, scope: ScopeMode) -> StoreContext:
        if scope == "global":
            return StoreContext(scope="global", database_path=SQLiteDatabase.default_path())

        root = self.find_project_root()
        if root is not None:
            return StoreContext(
                scope="project",
                database_path=root / PROJECT_DIR / PROJECT_DB,
                project_root=root,
            )

        if scope == "project":
            raise ProjectNotFoundError("project is not initialized; run `pmpt project init`")

        return StoreContext(scope="global", database_path=SQLiteDatabase.default_path())

    def find_project_root(self) -> Path | None:
        current = self._cwd
        candidates = [current, *current.parents]
        for path in candidates:
            if (path / PROJECT_DIR).is_dir():
                return path
        return None
