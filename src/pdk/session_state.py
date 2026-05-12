from __future__ import annotations

from pathlib import Path

from .command_support import CliError


SESSION_STATE_FILE = "session.md"


def session_state_path(project_root: Path) -> Path:
    return project_root / ".pdk" / SESSION_STATE_FILE


def save_session_state(project_root: Path, markdown: str) -> Path:
    path = session_state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def load_session_state(project_root: Path) -> str:
    path = session_state_path(project_root)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CliError("session state not found; run `pdk session build MODULE` first") from exc
