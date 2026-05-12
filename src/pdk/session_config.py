from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any

from .command_support import CliError
from .context_config import CONTEXT_CONFIG
from .context_models import ContextModule


@dataclass(frozen=True)
class SessionConfig:
    path: Path
    root: str
    default_modules: tuple[str, ...]
    file_detail: str
    compact: bool
    budget: int | None
    redact: bool
    modules: tuple[ContextModule, ...]


STARTER_MODULES: tuple[ContextModule, ...] = (
    ContextModule("base", "Stable personal or project background.", dirs=("context/base",)),
    ContextModule(
        "food",
        "Nutrition, meals, preferences, and food routines.",
        dirs=("context/food",),
        depends_on=("base",),
    ),
    ContextModule(
        "sport",
        "Training, recovery, and movement context.",
        dirs=("context/sport",),
        depends_on=("base",),
    ),
    ContextModule(
        "study",
        "Learning goals, subjects, exams, and study plans.",
        dirs=("context/study",),
        depends_on=("base",),
    ),
    ContextModule(
        "work",
        "Work projects, responsibilities, and decisions.",
        dirs=("context/work",),
        depends_on=("base",),
    ),
)
DEFAULT_SESSION_MODULES = ("base",)
DEFAULT_SESSION_ROOT = "context"
DEFAULT_SESSION_FILE_DETAIL = "full"
DEFAULT_SESSION_COMPACT = True
DEFAULT_SESSION_BUDGET = 16000
DEFAULT_SESSION_REDACT = False


def starter_modules_for(base_dir: str = "context") -> tuple[ContextModule, ...]:
    base = base_dir.rstrip("/") or "context"
    return tuple(
        ContextModule(
            name=module.name,
            description=module.description,
            dirs=(f"{base}/{module.name}",) if module.name != "study" else (f"{base}/study",),
            files=module.files,
            include_patterns=module.include_patterns,
            exclude_patterns=module.exclude_patterns,
            depends_on=module.depends_on,
        )
        for module in STARTER_MODULES
    )


def _string_list(value: Any, *, key: str, path: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CliError(f"malformed context config {path}: session field `{key}` must be a list of strings")
    return tuple(value)


def _optional_string(value: Any, *, key: str, path: Path) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CliError(f"malformed context config {path}: session field `{key}` must be a string")
    return value


def _string_value(value: Any, *, key: str, path: Path, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise CliError(f"malformed context config {path}: session field `{key}` must be a string")
    return value.strip()


def _bool_value(value: Any, *, key: str, path: Path, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise CliError(f"malformed context config {path}: session field `{key}` must be true or false")
    return value


def _optional_int(value: Any, *, key: str, path: Path) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise CliError(f"malformed context config {path}: session field `{key}` must be an integer")
    return value


def _file_detail(value: Any, *, path: Path) -> str:
    detail = _string_value(value, key="file_detail", path=path, default=DEFAULT_SESSION_FILE_DETAIL)
    if detail not in ("summary", "full"):
        raise CliError(f"malformed context config {path}: session field `file_detail` must be summary or full")
    return detail


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except FileNotFoundError as exc:
        raise CliError("session requires a project; run `pdk session init` first") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CliError(f"malformed context config {path}: {exc}") from exc


def load_session_config(project_root: Path) -> SessionConfig:
    path = project_root / ".pdk" / CONTEXT_CONFIG
    payload = _load_payload(path)
    session = payload.get("session")
    if not isinstance(session, dict):
        raise CliError(f"session config not found: {path}")

    default_modules = _string_list(session.get("default_modules"), key="default_modules", path=path)
    modules_section = session.get("modules", {})
    if not isinstance(modules_section, dict):
        raise CliError(f"malformed context config {path}: missing [session.modules.NAME]")

    modules: list[ContextModule] = []
    for name, raw_module in modules_section.items():
        if not isinstance(raw_module, dict):
            raise CliError(f"malformed context config {path}: session module `{name}` must be a table")
        normalized_name = str(name).strip()
        if not normalized_name:
            raise CliError(f"malformed context config {path}: session module name cannot be empty")
        modules.append(
            ContextModule(
                name=normalized_name,
                description=_optional_string(raw_module.get("description"), key="description", path=path),
                dirs=_string_list(raw_module.get("dirs"), key=f"modules.{name}.dirs", path=path),
                files=_string_list(raw_module.get("files"), key=f"modules.{name}.files", path=path),
                include_patterns=_string_list(raw_module.get("include"), key=f"modules.{name}.include", path=path),
                exclude_patterns=_string_list(raw_module.get("exclude"), key=f"modules.{name}.exclude", path=path),
                depends_on=_string_list(raw_module.get("depends_on"), key=f"modules.{name}.depends_on", path=path),
            )
        )
    budget = _optional_int(session.get("budget"), key="budget", path=path)
    return SessionConfig(
        path=path,
        root=_string_value(session.get("root"), key="root", path=path, default=DEFAULT_SESSION_ROOT),
        default_modules=default_modules or DEFAULT_SESSION_MODULES,
        file_detail=_file_detail(session.get("file_detail"), path=path),
        compact=_bool_value(session.get("compact"), key="compact", path=path, default=DEFAULT_SESSION_COMPACT),
        budget=DEFAULT_SESSION_BUDGET if budget is None else budget,
        redact=_bool_value(session.get("redact"), key="redact", path=path, default=DEFAULT_SESSION_REDACT),
        modules=tuple(modules),
    )


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_quote(value) for value in values) + "]"


def _render_session_block(config: SessionConfig) -> str:
    lines = [
        "[session]",
        f"root = {_quote(config.root)}",
        f"default_modules = {_array(config.default_modules)}",
        f"file_detail = {_quote(config.file_detail)}",
        f"compact = {str(config.compact).lower()}",
        f"budget = {config.budget}",
        f"redact = {str(config.redact).lower()}",
        "",
    ]
    for module in config.modules:
        lines.extend([f"[session.modules.{module.name}]", f"description = {_quote(module.description or '')}"])
        if module.dirs:
            lines.append(f"dirs = {_array(module.dirs)}")
        if module.files:
            lines.append(f"files = {_array(module.files)}")
        if module.depends_on:
            lines.append(f"depends_on = {_array(module.depends_on)}")
        if module.include_patterns:
            lines.append(f"include = {_array(module.include_patterns)}")
        if module.exclude_patterns:
            lines.append(f"exclude = {_array(module.exclude_patterns)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _without_session_blocks(text: str) -> str:
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            table_name = stripped.strip("[]").strip()
            skipping = table_name == "session" or table_name.startswith("session.")
        if not skipping:
            kept.append(line)
    return "\n".join(kept).rstrip() + "\n"


def _merged_session(
    project_root: Path,
    root: str,
    starter_modules: tuple[ContextModule, ...],
) -> SessionConfig:
    path = project_root / ".pdk" / CONTEXT_CONFIG
    try:
        current = load_session_config(project_root)
    except CliError as exc:
        if "session config not found" not in str(exc) and "session requires a project" not in str(exc):
            raise
        return SessionConfig(
            path=path,
            root=root,
            default_modules=DEFAULT_SESSION_MODULES,
            file_detail=DEFAULT_SESSION_FILE_DETAIL,
            compact=DEFAULT_SESSION_COMPACT,
            budget=DEFAULT_SESSION_BUDGET,
            redact=DEFAULT_SESSION_REDACT,
            modules=starter_modules,
        )

    by_name = {module.name: module for module in current.modules}
    for starter in starter_modules:
        existing = by_name.get(starter.name)
        if existing is None:
            by_name[starter.name] = starter
            continue
        by_name[starter.name] = ContextModule(
            name=existing.name,
            description=existing.description or starter.description,
            dirs=existing.dirs or starter.dirs,
            files=existing.files or starter.files,
            include_patterns=existing.include_patterns,
            exclude_patterns=existing.exclude_patterns,
            depends_on=existing.depends_on or starter.depends_on,
        )

    ordered_names = [module.name for module in starter_modules]
    ordered_names.extend(name for name in by_name if name not in ordered_names)
    return SessionConfig(
        path=current.path,
        root=current.root or root,
        default_modules=current.default_modules or DEFAULT_SESSION_MODULES,
        file_detail=current.file_detail,
        compact=current.compact,
        budget=current.budget,
        redact=current.redact,
        modules=tuple(by_name[name] for name in ordered_names),
    )


def write_starter_session_config(project_root: Path, *, base_dir: str = "context") -> Path:
    path = project_root / ".pdk" / CONTEXT_CONFIG
    config = _merged_session(project_root, base_dir, starter_modules_for(base_dir))
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    base = _without_session_blocks(existing) if existing else ""
    separator = "\n" if base.strip() else ""
    path.write_text(base.rstrip() + separator + _render_session_block(config), encoding="utf-8")
    return path
