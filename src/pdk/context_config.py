from __future__ import annotations

import argparse
from pathlib import Path
import tomllib
from typing import Any

from .command_support import CliError, _context, _project_selection
from .context_models import ContextModule, ContextOptions
from .project import ProjectNotFoundError, ProjectResolver
from .store import PromptStore


CONTEXT_DEFAULT_INCLUDES = frozenset({"prompts", "notes", "comments"})
CONTEXT_OPTIONAL_INCLUDES = frozenset({"usage", "versions"})
CONTEXT_INCLUDE_NAMES = CONTEXT_DEFAULT_INCLUDES | CONTEXT_OPTIONAL_INCLUDES
CONTEXT_CONFIG = "context.toml"


def _split_include_value(raw: str) -> set[str]:
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _is_context_include(raw: str) -> bool:
    parts = _split_include_value(raw)
    return bool(parts) and parts.issubset(CONTEXT_INCLUDE_NAMES)


def parse_context_includes(raw_values: list[str] | None) -> frozenset[str]:
    if not raw_values:
        return CONTEXT_DEFAULT_INCLUDES
    requested: set[str] = set()
    for raw in raw_values:
        if _is_context_include(raw):
            requested.update(_split_include_value(raw))
    unknown = requested - CONTEXT_INCLUDE_NAMES
    if unknown:
        raise CliError(f"unknown context include: {', '.join(sorted(unknown))}")
    return CONTEXT_DEFAULT_INCLUDES | requested


def parse_file_include_patterns(raw_values: list[str] | None) -> tuple[str, ...]:
    if not raw_values:
        return ()
    return tuple(raw for raw in raw_values if not _is_context_include(raw))


def _profile_project_root(args: argparse.Namespace) -> Path | None:
    if not getattr(args, "profile", None):
        return None
    try:
        return ProjectResolver().resolve("project").project_root
    except ProjectNotFoundError as exc:
        raise CliError("context profiles require a project; run `pdk project init` first") from exc


def _string_list(value: Any, *, key: str, path: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CliError(f"malformed context config {path}: context profile field `{key}` must be a list of strings")
    return tuple(value)


def _optional_bool(value: Any, *, key: str, path: Path) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise CliError(f"malformed context config {path}: context profile field `{key}` must be true or false")
    return value


def _optional_string(value: Any, *, key: str, path: Path) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CliError(f"malformed context config {path}: context profile field `{key}` must be a string")
    return value


def _optional_int(value: Any, *, key: str, path: Path) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise CliError(f"malformed context config {path}: context profile field `{key}` must be an integer")
    return value


def _optional_file_detail(value: Any, *, path: Path) -> str | None:
    if value is None:
        return None
    if value not in ("summary", "full"):
        raise CliError(
            f"malformed context config {path}: context profile field `file_detail` must be summary or full"
        )
    return str(value)


def _module_list(value: Any, *, path: Path) -> tuple[ContextModule, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise CliError(f"malformed context config {path}: context profile field `modules` must be a list of tables")

    modules: list[ContextModule] = []
    seen: set[str] = set()
    for index, raw_module in enumerate(value, start=1):
        name = raw_module.get("name")
        if not isinstance(name, str) or not name.strip():
            raise CliError(f"malformed context config {path}: context module #{index} needs a non-empty `name`")
        normalized_name = name.strip()
        if normalized_name in seen:
            raise CliError(f"malformed context config {path}: duplicate context module `{normalized_name}`")
        seen.add(normalized_name)
        modules.append(
            ContextModule(
                name=normalized_name,
                description=_optional_string(raw_module.get("description"), key="description", path=path),
                dirs=_string_list(raw_module.get("dirs"), key="dirs", path=path),
                files=_string_list(raw_module.get("files"), key="files", path=path),
                include_patterns=_string_list(raw_module.get("include"), key="include", path=path),
                exclude_patterns=_string_list(raw_module.get("exclude"), key="exclude", path=path),
                depends_on=_string_list(raw_module.get("depends_on"), key="depends_on", path=path),
            )
        )
    return tuple(modules)


def _load_profile(args: argparse.Namespace, project_root: Path | None) -> dict[str, Any]:
    name = getattr(args, "profile", None)
    if not name:
        return {}
    if project_root is None:
        raise CliError("context profiles require a project; run `pdk project init` first")
    path = project_root / ".pdk" / CONTEXT_CONFIG
    try:
        with path.open("rb") as file:
            payload = tomllib.load(file)
    except FileNotFoundError as exc:
        raise CliError(f"context profile not found: {name}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CliError(f"malformed context config {path}: {exc}") from exc

    context_section = payload.get("context")
    if not isinstance(context_section, dict):
        raise CliError(f"malformed context config {path}: missing [context.{name}]")
    profile = context_section.get(name)
    if not isinstance(profile, dict):
        raise CliError(f"context profile not found: {name}")
    return {
        "dirs": _string_list(profile.get("dirs"), key="dirs", path=path),
        "files": _string_list(profile.get("files"), key="files", path=path),
        "exclude": _string_list(profile.get("exclude"), key="exclude", path=path),
        "include": _string_list(profile.get("include"), key="include", path=path),
        "file_detail": _optional_file_detail(profile.get("file_detail"), path=path),
        "budget": _optional_int(profile.get("budget"), key="budget", path=path),
        "redact": _optional_bool(profile.get("redact"), key="redact", path=path),
        "compact": _optional_bool(profile.get("compact"), key="compact", path=path),
        "modules": _module_list(profile.get("modules"), path=path),
    }


def _profile_paths(values: tuple[str, ...], project_root: Path | None) -> tuple[str, ...]:
    if project_root is None:
        return values
    return tuple(str(Path(value)) if Path(value).is_absolute() else str(project_root / value) for value in values)


def _profile_module_paths(modules: tuple[ContextModule, ...], project_root: Path | None) -> tuple[ContextModule, ...]:
    if project_root is None:
        return modules
    return tuple(
        ContextModule(
            name=module.name,
            description=module.description,
            dirs=_profile_paths(module.dirs, project_root),
            files=_profile_paths(module.files, project_root),
            include_patterns=module.include_patterns,
            exclude_patterns=module.exclude_patterns,
            depends_on=module.depends_on,
        )
        for module in modules
    )


def context_options_from_args(args: argparse.Namespace, store: PromptStore) -> ContextOptions:
    store_context = _context(args)
    profile_root = _profile_project_root(args)
    profile = _load_profile(args, profile_root)
    project_id, project_filter, project_name = _project_selection(args, store)
    include_values = [*profile.get("include", ()), *(args.include or ())]
    modules = _profile_module_paths(profile.get("modules", ()), profile_root)
    return ContextOptions(
        project_id=project_id,
        project_filter=project_filter,
        project_name=project_name,
        includes=parse_context_includes(include_values),
        since=args.since,
        redact=bool(profile.get("redact") or args.redact),
        privacy_profile=args.privacy_profile,
        privacy_model=args.privacy_model,
        privacy_model_name=args.privacy_model_name,
        privacy_model_threshold=args.privacy_model_threshold,
        budget=args.budget if args.budget is not None else profile.get("budget"),
        database=str(store.path),
        file_targets=(*_profile_paths(profile.get("files", ()), profile_root), *(args.file or ())),
        dir_targets=(*_profile_paths(profile.get("dirs", ()), profile_root), *(args.dir or ())),
        file_detail=args.file_detail or profile.get("file_detail") or "summary",
        file_include_patterns=parse_file_include_patterns(include_values),
        file_exclude_patterns=(*profile.get("exclude", ()), *(args.exclude or ())),
        ignore_root=profile_root or (store_context.project_root if store_context.scope == "project" else None),
        modules=modules,
        compact=bool(profile.get("compact") or args.compact),
    )
