from __future__ import annotations

import argparse
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from .editor import EditorError, TextEditor
from .models import TagSet
from .privacy import PrivacyConfigError, PrivacyModelError, detect_private_data
from .project import ProjectNotFoundError, ProjectResolver
from .security import SecurityError, secret_warnings
from .sources import SourceError, TextSource, read_sources
from .store import NamedProjectNotFoundError, NoteNotFoundError, PromptNotFoundError, PromptStore
from .summary import SummaryModelError
from .tokens import token_summary
from .ui import StatusReporter
from .variables import VariableFillCancelled, VariablePrompter


class CliError(Exception):
    pass


def _split_tags(values: list[str] | None) -> list[str]:
    return list(TagSet.from_values(values or ()).names)


def _reporter(args: argparse.Namespace, stderr: TextIO) -> StatusReporter:
    return StatusReporter(stderr, args.color)


def _warn_secrets(args: argparse.Namespace, stderr: TextIO, label: str, text: str) -> None:
    warnings = secret_warnings(text)
    if warnings:
        _reporter(args, stderr).warning(f"{label} may contain secret-like data: {', '.join(warnings)}")


def _context(args: argparse.Namespace):
    return ProjectResolver().resolve(args.scope)


def _store(args: argparse.Namespace) -> PromptStore:
    return PromptStore(_context(args).database_path)


def _project_selection(
    args: argparse.Namespace,
    store: PromptStore,
    *,
    use_active: bool = True,
) -> tuple[int | None, bool, str | None]:
    if getattr(args, "no_project", False):
        return None, True, None
    project_name = getattr(args, "project", None) or getattr(args, "project_name", None)
    if project_name:
        project = store.get_project(project_name)
        return project.id, True, project.name
    if use_active:
        active = store.active_project()
        if active is not None:
            return active.id, True, active.name
    return None, False, None


def _project_description_arg(values: list[str] | None) -> str:
    return " ".join(values or ()).strip()


def _optional_words(values: list[str] | None) -> str | None:
    text = " ".join(values or ()).strip()
    return text or None


def _note_form(title: str | None, body: str) -> str:
    return f"Title: {title or ''}\n--- body ---\n{body}"


def _parse_note_form(text: str, current_title: str | None) -> tuple[str | None, str]:
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].startswith("Title:"):
        return current_title, text
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "--- body ---":
            title = lines[0][len("Title:") :].strip() or None
            return title, "".join(lines[index + 1 :])
    return current_title, text


def _project_form(name: str, description: str) -> str:
    return f"Name: {name}\nDescription:\n{description}"


def _parse_project_form(text: str, current_name: str, current_description: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    if not lines or not lines[0].startswith("Name:"):
        return current_name, text.strip()
    name = lines[0][len("Name:") :].strip() or current_name
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "Description:":
            return name, "".join(lines[index + 1 :]).strip()
    return name, current_description


def _fill_variables(args: argparse.Namespace, body: str, stdin: TextIO, stderr: TextIO) -> str:
    prompter = VariablePrompter(TextEditor.from_environment(), stdin, stderr, color=args.color)
    return prompter.fill(body)


def _write_token_summary(template: str, rendered: str, stdout: TextIO, stderr: TextIO) -> None:
    if stdout.isatty() and rendered and not rendered.endswith("\n"):
        print(file=stderr)
    print(token_summary(template, rendered), file=stderr)


def _read_text_source(args: argparse.Namespace, stdin: TextIO) -> tuple[str, str]:
    paths = getattr(args, "paths", None) or []
    if paths:
        sources = read_sources(paths, recursive=not getattr(args, "no_recursive", False))
        if len(sources) != 1:
            raise CliError("this command expects one input; use `pdk scan` for multiple files")
        return sources[0].label, sources[0].text
    if getattr(args, "stdin", False):
        return "stdin", stdin.read()
    if getattr(args, "file", None):
        path = Path(args.file).expanduser()
        return str(path), path.read_text(encoding="utf-8")
    return "clipboard", _read_clipboard()


def _read_text_sources(args: argparse.Namespace, stdin: TextIO) -> list[TextSource]:
    paths = getattr(args, "paths", None) or []
    if paths:
        return read_sources(paths, recursive=not getattr(args, "no_recursive", False))
    if getattr(args, "stdin", False):
        return [TextSource("stdin", stdin.read())]
    if getattr(args, "file", None):
        path = Path(args.file).expanduser()
        return [TextSource(str(path), path.read_text(encoding="utf-8"))]
    return [TextSource("clipboard", _read_clipboard())]


def _read_clipboard() -> str:
    if shutil.which("pbpaste") is None:
        raise CliError("clipboard command is not available")
    try:
        result = subprocess.run(
            ["pbpaste"],
            text=True,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise CliError("clipboard command failed") from exc
    return result.stdout


def _detect_for_args(args: argparse.Namespace, text: str):
    return detect_private_data(
        text,
        profile=getattr(args, "profile", None),
        use_model=getattr(args, "model", False),
        model_name=getattr(args, "model_name", None),
        model_threshold=getattr(args, "model_threshold", None),
    )


def _write_scan_table(rows: list[tuple[str, int, int, int, int, str]], stdout: TextIO) -> None:
    headers = ("source", "findings", "tokens", "lines", "chars", "types")
    widths = [max(len(headers[index]), *(len(str(row[index])) for row in rows)) for index in range(len(headers) - 1)]
    stdout.write(
        f"{headers[0].ljust(widths[0])}  "
        f"{headers[1].rjust(widths[1])}  "
        f"{headers[2].rjust(widths[2])}  "
        f"{headers[3].rjust(widths[3])}  "
        f"{headers[4].rjust(widths[4])}  "
        f"{headers[5]}\n"
    )
    for row in rows:
        stdout.write(
            f"{row[0].ljust(widths[0])}  "
            f"{str(row[1]).rjust(widths[1])}  "
            f"{str(row[2]).rjust(widths[2])}  "
            f"{str(row[3]).rjust(widths[3])}  "
            f"{str(row[4]).rjust(widths[4])}  "
            f"{row[5]}\n"
        )


def _short_timestamp(value: str | None) -> str:
    if value is None:
        return "-"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M")


CLI_ERRORS = (
    CliError,
    NamedProjectNotFoundError,
    NoteNotFoundError,
    PromptNotFoundError,
    ProjectNotFoundError,
    PrivacyConfigError,
    PrivacyModelError,
    SecurityError,
    SourceError,
    SummaryModelError,
    EditorError,
    VariableFillCancelled,
    ValidationError,
)


def cli_error_message(exc: Exception) -> str:
    if isinstance(exc, PromptNotFoundError):
        return f"prompt not found: {exc.args[0]}"
    if isinstance(exc, NamedProjectNotFoundError):
        return f"project not found: {exc.args[0]}"
    if isinstance(exc, NoteNotFoundError):
        return f"note not found: {exc.args[0]}"
    if isinstance(exc, ValidationError):
        return str(exc.errors()[0]["msg"])
    return str(exc)


def report_cli_error(args: argparse.Namespace, stderr: TextIO, exc: Exception) -> None:
    _reporter(args, stderr).error(cli_error_message(exc))
