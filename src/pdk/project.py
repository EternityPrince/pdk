from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .database import SQLiteDatabase

PROJECT_DIR = ".pdk"
LEGACY_PROJECT_DIR = ".pmpt"
PROJECT_DB = "prompts.sqlite3"
CONTEXT_CONFIG_TEMPLATE = """[context.default]
dirs = ["src", "docs"]
files = ["README.md"]
exclude = [
  "**/.venv/**",
  "**/node_modules/**",
  "**/__pycache__/**",
  "**/.env*",
]
file_detail = "summary"
budget = 12000
redact = true

[context.docs]
dirs = ["docs"]
files = ["README.md"]
file_detail = "summary"
budget = 8000
redact = true

[context.code]
dirs = ["src"]
exclude = ["**/tests/fixtures/**"]
file_detail = "summary"
budget = 16000
redact = true
"""
PDKIGNORE_TEMPLATE = """.venv/
venv/
node_modules/
__pycache__/
dist/
build/
target/
.cache/
.DS_Store
.env
.env.*
*.pem
*.key
*.p12
*.crt
"""

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
        context_config = project_dir / "context.toml"
        if not context_config.exists():
            context_config.write_text(CONTEXT_CONFIG_TEMPLATE, encoding="utf-8")
        pdkignore = root / ".pdkignore"
        if not pdkignore.exists():
            pdkignore.write_text(PDKIGNORE_TEMPLATE, encoding="utf-8")
        db_path = project_dir / PROJECT_DB
        SQLiteDatabase(db_path)
        return StoreContext(scope="project", database_path=db_path, project_root=root)

    def resolve(self, scope: ScopeMode) -> StoreContext:
        if scope == "global":
            return StoreContext(scope="global", database_path=SQLiteDatabase.default_path())

        root = self.find_project_root()
        if root is not None:
            project_dir = self._project_dir_for(root)
            return StoreContext(
                scope="project",
                database_path=project_dir / PROJECT_DB,
                project_root=root,
            )

        if scope == "project":
            raise ProjectNotFoundError("project is not initialized; run `pdk project init`")

        return StoreContext(scope="global", database_path=SQLiteDatabase.default_path())

    def find_project_root(self) -> Path | None:
        current = self._cwd
        candidates = [current, *current.parents]
        for path in candidates:
            if self._project_dir_for(path).is_dir():
                return path
        return None

    def _project_dir_for(self, root: Path) -> Path:
        project_dir = root / PROJECT_DIR
        if project_dir.is_dir():
            return project_dir
        legacy_project_dir = root / LEGACY_PROJECT_DIR
        if legacy_project_dir.is_dir():
            return legacy_project_dir
        return project_dir
