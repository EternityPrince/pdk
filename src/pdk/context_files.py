from __future__ import annotations

from dataclasses import dataclass, replace
from fnmatch import fnmatch
from pathlib import Path

from .command_support import CliError
from .context_models import ContextFile, ContextOptions
from .file_index import FileIndex, FileRecord
from .text_analysis import extractive_summary


BUILTIN_DIR_EXCLUDES = (
    ".git/",
    ".venv/",
    "venv/",
    "node_modules/",
    "__pycache__/",
    "dist/",
    "build/",
    "target/",
    ".cache/",
    ".DS_Store",
    "*.pyc",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.crt",
)


@dataclass(frozen=True)
class FileCandidate:
    record: FileRecord
    from_dir: bool = False
    module_name: str | None = None
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()


def _resolved_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _is_relative_to(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _relative_posix(path: Path, root: Path) -> str | None:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def _read_pdkignore(root: Path) -> tuple[str, ...]:
    path = root / ".pdkignore"
    if not path.exists():
        return ()
    patterns: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            patterns.append(stripped)
    return tuple(patterns)


def _directory_pattern_matches(path: Path, pattern: str, roots: tuple[Path, ...]) -> bool:
    directory_name = pattern.rstrip("/")
    if any(part == directory_name for part in path.parts):
        return True
    for root in roots:
        relative = _relative_posix(path, root)
        if relative is not None and (relative == directory_name or relative.startswith(directory_name + "/")):
            return True
    return False


def _glob_pattern_matches(path: Path, pattern: str, roots: tuple[Path, ...]) -> bool:
    normalized = pattern.strip()
    if not normalized:
        return False
    if normalized.endswith("/"):
        return _directory_pattern_matches(path, normalized, roots)

    full = path.as_posix()
    names = (path.name, full)
    if any(fnmatch(value, normalized) for value in names):
        return True

    rootless = normalized[1:] if normalized.startswith("/") else normalized
    for root in roots:
        relative = _relative_posix(path, root)
        if relative is None:
            continue
        if fnmatch(relative, rootless) or fnmatch(relative, f"**/{rootless}"):
            return True
    return False


def _matches_any(path: Path, patterns: tuple[str, ...], roots: tuple[Path, ...]) -> bool:
    return any(_glob_pattern_matches(path, pattern, roots) for pattern in patterns)


def _dir_candidates(
    index: FileIndex,
    dir_targets: tuple[str, ...],
    *,
    module_name: str | None = None,
    include_patterns: tuple[str, ...] = (),
    exclude_patterns: tuple[str, ...] = (),
) -> list[FileCandidate]:
    candidates: list[FileCandidate] = []
    records = index.files()
    for target in dir_targets:
        directory = _resolved_path(target)
        matches = [
            record
            for record in records
            if _is_relative_to(_resolved_path(record.path), directory)
        ]
        if not matches:
            raise CliError(f"no indexed files found under {target}; run `pdk index DIR` first")
        candidates.extend(
            FileCandidate(
                record,
                from_dir=True,
                module_name=module_name,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
            )
            for record in matches
        )
    return candidates


def _explicit_candidate(
    index: FileIndex,
    target: str,
    *,
    module_name: str | None = None,
    include_patterns: tuple[str, ...] = (),
    exclude_patterns: tuple[str, ...] = (),
) -> FileCandidate:
    try:
        return FileCandidate(
            index.get_file(target),
            from_dir=False,
            module_name=module_name,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
    except KeyError:
        target_path = _resolved_path(target)
        for record in index.files():
            if _resolved_path(record.path) == target_path:
                return FileCandidate(
                    record,
                    from_dir=False,
                    module_name=module_name,
                    include_patterns=include_patterns,
                    exclude_patterns=exclude_patterns,
                )
    raise CliError(f"indexed file not found: {target}; run `pdk index TARGET` first")


def resolve_file_target(index: FileIndex, target: str, *, detail: str = "summary") -> ContextFile:
    return context_file_from_record(index, _explicit_candidate(index, target).record, detail=detail)


def context_file_from_record(
    index: FileIndex,
    record: FileRecord,
    *,
    detail: str = "summary",
    module_names: tuple[str, ...] = (),
) -> ContextFile:
    text = index.file_text(record.id)
    summary = record.summary if record.summary else extractive_summary(text)
    return ContextFile(
        id=record.id,
        path=record.path,
        kind=record.kind,
        size_bytes=record.size_bytes,
        mtime=record.mtime,
        sha256=record.sha256,
        indexed_at=record.indexed_at,
        status=record.status,
        token_count=record.token_count,
        line_count=record.line_count,
        char_count=record.char_count,
        finding_count=record.finding_count,
        detail=detail,
        summary=summary,
        text=text if detail == "full" else None,
        module_names=module_names,
    )


def collect_context_files(index: FileIndex, options: ContextOptions) -> tuple[ContextFile, ...]:
    candidates = [_explicit_candidate(index, target) for target in options.file_targets]
    candidates.extend(_dir_candidates(index, options.dir_targets))
    for module in options.modules:
        candidates.extend(
            _explicit_candidate(
                index,
                target,
                module_name=module.name,
                include_patterns=module.include_patterns,
                exclude_patterns=module.exclude_patterns,
            )
            for target in module.files
        )
        candidates.extend(
            _dir_candidates(
                index,
                module.dirs,
                module_name=module.name,
                include_patterns=module.include_patterns,
                exclude_patterns=module.exclude_patterns,
            )
        )

    ignore_root = options.ignore_root or Path.cwd()
    module_roots = tuple(_resolved_path(target) for module in options.modules for target in module.dirs)
    cli_roots = (
        tuple(_resolved_path(target) for target in options.dir_targets)
        + module_roots
        + (Path.cwd().resolve(), ignore_root)
    )
    pdkignore_patterns = _read_pdkignore(ignore_root)
    filtered: list[FileCandidate] = []
    for candidate in candidates:
        path = _resolved_path(candidate.record.path)
        if candidate.from_dir and _matches_any(path, BUILTIN_DIR_EXCLUDES, cli_roots):
            continue
        if candidate.from_dir and _matches_any(path, pdkignore_patterns, (ignore_root, Path.cwd().resolve())):
            continue
        if _matches_any(path, options.file_exclude_patterns, cli_roots):
            continue
        if _matches_any(path, candidate.exclude_patterns, cli_roots):
            continue
        if options.file_include_patterns and not _matches_any(path, options.file_include_patterns, cli_roots):
            continue
        if candidate.include_patterns and not _matches_any(path, candidate.include_patterns, cli_roots):
            continue
        filtered.append(candidate)

    seen: dict[int, int] = {}
    files: list[ContextFile] = []
    for candidate in filtered:
        module_names = (candidate.module_name,) if candidate.module_name else ()
        if candidate.record.id in seen:
            index_in_files = seen[candidate.record.id]
            existing = files[index_in_files]
            merged_modules = tuple(dict.fromkeys((*existing.module_names, *module_names)))
            if merged_modules != existing.module_names:
                files[index_in_files] = replace(existing, module_names=merged_modules)
            continue
        seen[candidate.record.id] = len(files)
        files.append(
            context_file_from_record(
                index,
                candidate.record,
                detail=options.file_detail,
                module_names=module_names,
            )
        )
    return tuple(files)
