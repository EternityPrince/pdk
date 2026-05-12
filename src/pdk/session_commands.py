from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import TextIO

from .command_support import CliError, _detect_for_args, _reporter
from .context_builder import build_context_document
from .context_commands import _redact_document, _warn_budget, _warn_context_secrets
from .context_models import ContextDocument, ContextModule, ContextOptions
from .context_rendering import render_context_compact_markdown, render_context_markdown
from .file_workflows import index_paths
from .interactive import Clipboard
from .project import ProjectNotFoundError, ProjectResolver
from .session_config import SessionConfig, load_session_config, write_starter_session_config
from .tokens import count_tokens


STARTER_FILES = {
    "base/profile.md": "# Profile\n\n",
    "base/preferences.md": "# Preferences\n\n",
    "base/goals.md": "# Goals\n\n",
    "food/nutrition.md": "# Nutrition\n\n",
    "sport/training.md": "# Training\n\n",
    "study/learning.md": "# Learning\n\n",
    "work/projects.md": "# Projects\n\n",
}


class _EmptyStore:
    def list(self, **kwargs):
        return []

    def notes(self, **kwargs):
        return []

    def usage(self, **kwargs):
        return []


def _project_root_or_error() -> Path:
    try:
        context = ProjectResolver().resolve("project")
    except ProjectNotFoundError as exc:
        raise CliError("session requires a project; run `pdk session init` first") from exc
    if context.project_root is None:
        raise CliError("session requires a project; run `pdk session init` first")
    return context.project_root


def _session_path(project_root: Path, value: str | None) -> Path:
    if value is None:
        return project_root / "context"
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root / path


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return str(path)


def _module_targets(module: ContextModule) -> str:
    targets = [*(f"dir:{value}" for value in module.dirs), *(f"file:{value}" for value in module.files)]
    return ", ".join(targets) if targets else "-"


def _target_paths(modules: tuple[ContextModule, ...]) -> list[str]:
    return [
        *(path for module in modules for path in module.dirs),
        *(path for module in modules for path in module.files),
    ]


def _module_names(modules: tuple[ContextModule, ...]) -> str:
    return ", ".join(module.name for module in modules)


def _resolve_module_paths(modules: tuple[ContextModule, ...], project_root: Path) -> tuple[ContextModule, ...]:
    def resolve(values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(str(Path(value)) if Path(value).is_absolute() else str(project_root / value) for value in values)

    return tuple(
        replace(module, dirs=resolve(module.dirs), files=resolve(module.files))
        for module in modules
    )


def _selected_modules(
    names: tuple[str, ...],
    modules: tuple[ContextModule, ...],
    defaults: tuple[str, ...],
) -> tuple[ContextModule, ...]:
    by_name = {module.name: module for module in modules}
    if "all" in names:
        requested = tuple(module.name for module in modules)
    else:
        requested = defaults if not names else tuple(dict.fromkeys((*defaults, *names)))

    selected: list[ContextModule] = []
    visiting: set[str] = set()
    seen: set[str] = set()

    def add(name: str) -> None:
        if name in seen:
            return
        if name not in by_name:
            raise CliError(f"unknown session module: {name}")
        if name in visiting:
            raise CliError(f"cyclic session module dependency: {name}")
        visiting.add(name)
        module = by_name[name]
        for dependency in module.depends_on:
            add(dependency)
        visiting.remove(name)
        seen.add(name)
        selected.append(module)

    for name in requested:
        add(name)
    return tuple(selected)


def _render_session_markdown(
    args: argparse.Namespace,
    document: ContextDocument,
    modules: tuple[ContextModule, ...],
) -> str:
    context_markdown = (
        render_context_compact_markdown(document) if document.options.compact else render_context_markdown(document)
    ).rstrip()
    lines = ["# Prompt Deck Session", ""]
    if args.question:
        lines.extend(["## Question", "", args.question, ""])
    lines.extend(["## Included Modules", ""])
    lines.extend(f"- {module.name}" for module in modules)
    lines.extend(["", "## Context", "", context_markdown, ""])
    return "\n".join(lines)


def _write_session_dry_run(
    args: argparse.Namespace,
    document: ContextDocument,
    rendered: str,
    modules: tuple[ContextModule, ...],
    stdout: TextIO,
) -> None:
    tokens = count_tokens(rendered)
    paths = _target_paths(modules)
    stdout.write("session dry run\n")
    stdout.write("modules\t" + _module_names(modules) + "\n")
    stdout.write("paths\t" + (", ".join(paths) if paths else "-") + "\n")
    stdout.write(f"files\t{len(document.files)}\n")
    stdout.write("file_sources\t" + (", ".join(file.path for file in document.files) if document.files else "-") + "\n")
    stdout.write(f"file_detail\t{document.options.file_detail}\n")
    stdout.write(f"compact\t{'yes' if document.options.compact else 'no'}\n")
    stdout.write(f"estimated_tokens\t{tokens}\n")
    if document.options.budget is not None:
        status = "over" if tokens > document.options.budget else "within"
        stdout.write(f"budget\t{document.options.budget}\n")
        stdout.write(f"budget_status\t{status}\n")


def cmd_session_init(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    resolver = ProjectResolver()
    try:
        context = resolver.resolve("project")
    except ProjectNotFoundError:
        context = resolver.initialize()
    if context.project_root is None:
        raise CliError("session requires a project root")

    root = _session_path(context.project_root, args.path)
    for relative, body in STARTER_FILES.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(body, encoding="utf-8")

    config_path = write_starter_session_config(context.project_root, base_dir=_display_path(root, context.project_root))
    _reporter(args, stderr).success(f"Initialized session context at {_display_path(root, context.project_root)}")
    _reporter(args, stderr).success(f"Updated session config {config_path}")
    return 0


def cmd_session_list(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    project_root = _project_root_or_error()
    config = load_session_config(project_root)
    stdout.write(f"root\t{config.root}\n")
    stdout.write(f"default_modules\t{', '.join(config.default_modules)}\n")
    stdout.write(f"file_detail\t{config.file_detail}\n")
    stdout.write(f"compact\t{'yes' if config.compact else 'no'}\n")
    if config.budget is not None:
        stdout.write(f"budget\t{config.budget}\n")
    stdout.write(f"redact\t{'yes' if config.redact else 'no'}\n\n")
    rows = [
        (module.name, _module_targets(module), ", ".join(module.depends_on) or "-", module.description or "-")
        for module in config.modules
    ]
    headers = ("name", "dirs/files", "depends_on", "description")
    widths = [max(len(headers[index]), *(len(row[index]) for row in rows)) for index in range(len(headers) - 1)]
    stdout.write(
        f"{headers[0].ljust(widths[0])}  "
        f"{headers[1].ljust(widths[1])}  "
        f"{headers[2].ljust(widths[2])}  "
        f"{headers[3]}\n"
    )
    for row in rows:
        stdout.write(f"{row[0].ljust(widths[0])}  {row[1].ljust(widths[1])}  {row[2].ljust(widths[2])}  {row[3]}\n")
    return 0


def _context_options(args: argparse.Namespace, config: SessionConfig, project_root: Path) -> ContextOptions:
    store_context = ProjectResolver().resolve("project")
    return ContextOptions(
        project_filter=True,
        includes=frozenset(),
        redact=config.redact or args.redact,
        budget=args.budget if args.budget is not None else config.budget,
        database=str(store_context.database_path),
        file_detail=args.file_detail or config.file_detail,
        ignore_root=project_root,
        compact=config.compact or args.compact,
    )


def _build_session_document(
    options: ContextOptions,
    modules: tuple[ContextModule, ...],
) -> ContextDocument:
    try:
        document = build_context_document(_EmptyStore(), replace(options, modules=modules))
    except CliError as exc:
        if "no indexed files found under" in str(exc) or "indexed file not found:" in str(exc):
            raise CliError(f"no files found for session modules: {_module_names(modules)}") from exc
        raise
    if not document.files:
        raise CliError(f"no files found for session modules: {_module_names(modules)}")
    return document


def cmd_session_build(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    if args.dry_run and args.copy:
        raise CliError("--dry-run cannot be combined with --copy")

    project_root = _project_root_or_error()
    config = load_session_config(project_root)
    modules = _selected_modules(tuple(args.modules or ()), config.modules, config.default_modules)
    resolved_modules = _resolve_module_paths(modules, project_root)

    if not args.no_index:
        targets = _target_paths(resolved_modules)
        if targets:
            index_paths(
                targets,
                recursive=True,
                chunk_tokens=1200,
                detector=lambda text: _detect_for_args(args, text),
            )

    options = _context_options(args, config, project_root)
    document = _build_session_document(options, resolved_modules)
    if options.redact:
        document = _redact_document(document)
    else:
        _warn_context_secrets(args, document, stderr)
    rendered = _render_session_markdown(args, document, modules)
    tokens = count_tokens(rendered)
    _warn_budget(args, stderr, tokens=tokens, budget=options.budget)

    if args.dry_run:
        _write_session_dry_run(args, document, rendered, modules, stdout)
        return 0
    if args.copy:
        try:
            copied = Clipboard().copy(rendered)
        except Exception as exc:
            raise CliError("clipboard command failed") from exc
        if not copied:
            raise CliError("clipboard command is not available")
        _reporter(args, stderr).success(f"Copied session to clipboard ({tokens} tokens)")
        return 0
    if args.output:
        Path(args.output).expanduser().write_text(rendered, encoding="utf-8")
        _reporter(args, stderr).success(f"Wrote session {args.output}")
        return 0
    stdout.write(rendered)
    return 0
