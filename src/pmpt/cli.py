from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from .editor import EditorError, TextEditor
from .interactive import InteractiveBrowser
from .models import Prompt, PromptStats, TagSet, UsageAction
from .project import ProjectNotFoundError, ProjectResolver
from .store import (
    NamedProjectNotFoundError,
    NoteNotFoundError,
    ProjectExistsError,
    PromptExistsError,
    PromptNotFoundError,
    PromptStore,
)
from .ui import ConsoleStyle, PromptFormatter, StatusReporter
from .variables import VariableFillCancelled, VariablePrompter


class CliError(Exception):
    pass


def _split_tags(values: list[str] | None) -> list[str]:
    return list(TagSet.from_values(values or ()).names)


def _reporter(args: argparse.Namespace, stderr: TextIO) -> StatusReporter:
    return StatusReporter(stderr, args.color)


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


def cmd_add(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    body = TextEditor.from_environment().read_or_edit(stdin)
    tags = _split_tags(args.tag)
    project_id, _, project_name = _project_selection(args, store)
    try:
        store.add(args.name, body, replace=args.replace, tags=tags, project_id=project_id)
    except PromptExistsError as exc:
        raise CliError(f"prompt already exists: {exc.args[0]}") from exc
    suffix = f" with tags: {', '.join(tags)}" if tags else ""
    if project_name:
        suffix += f" in project {project_name}"
    _reporter(args, stderr).success(f"Saved {args.name}{suffix}")
    return 0


def cmd_edit(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    prompt = store.get(args.name)
    updated = TextEditor.from_environment().edit(prompt.body)
    store.update(args.name, updated)
    _reporter(args, stderr).success(f"Updated {args.name}")
    return 0


def cmd_show(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    prompt = store.get(args.name)
    stdout.write(_fill_variables(args, prompt.body, stdin, stderr))
    store.record_usage(UsageAction.SHOW, [args.name])
    return 0


def _write_prompt_rows(prompts: list[Prompt], stdout: TextIO, formatter: PromptFormatter) -> None:
    for prompt in prompts:
        stdout.write(formatter.prompt_row(prompt))


def _short_timestamp(value: str | None) -> str:
    if value is None:
        return "-"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%Y-%m-%d %H:%M")


def _align_cell(value: str, width: int, align: str = "left") -> str:
    if align == "right":
        return value.rjust(width)
    return value.ljust(width)


def _tag_table_cell(prompt: Prompt, style: ConsoleStyle) -> str:
    if not prompt.tags:
        return "-"
    return " ".join(style.paint(f"#{tag}", "cyan") for tag in prompt.tags)


def _write_prompt_table(
    prompts: list[Prompt],
    stdout: TextIO,
    style: ConsoleStyle,
    stats_by_name: dict[str, PromptStats],
) -> None:
    def usage_count(prompt: Prompt) -> int:
        stats = stats_by_name.get(prompt.name)
        return stats.show_count if stats else 0

    ordered = sorted(
        prompts,
        key=lambda prompt: (-usage_count(prompt), prompt.name.casefold()),
    )
    headers = ("prompt", "uses", "edits", "feedback", "last used", "tags")
    rows = []
    for prompt in ordered:
        stats = stats_by_name.get(prompt.name)
        rows.append(
            (
                prompt.name,
                str(stats.show_count if stats else 0),
                str(stats.edit_count if stats else 0),
                str(stats.feedback_count if stats else 0),
                _short_timestamp(stats.last_used_at if stats else None),
                " ".join(f"#{tag}" for tag in prompt.tags) or "-",
            )
        )
    widths = [
        max([len(headers[index]), *(len(row[index]) for row in rows)])
        for index in range(len(headers) - 1)
    ]
    aligns = ("left", "right", "right", "right", "left")

    header = [
        style.paint(_align_cell(headers[index], widths[index], aligns[index]), "bold")
        for index in range(len(headers) - 1)
    ]
    header.append(style.paint(headers[-1], "bold"))
    stdout.write("  ".join(header) + "\n")

    for prompt, row in zip(ordered, rows, strict=True):
        cells = []
        for index, value in enumerate(row[:-1]):
            cell = _align_cell(value, widths[index], aligns[index])
            if index == 0:
                cell = style.paint(cell, "bold", "magenta")
            cells.append(cell)
        cells.append(_tag_table_cell(prompt, style))
        stdout.write("  ".join(cells) + "\n")


def cmd_list(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    style = ConsoleStyle(args.color, stdout)
    project_id, project_filter, _ = _project_selection(args, store)
    prompts = store.list(
        tags=_split_tags(args.tag),
        query=args.query,
        project_id=project_id,
        project_filter=project_filter,
    )
    stats_by_name = {
        stats.name: stats
        for stats in store.stats(project_id=project_id, project_filter=project_filter)
    }
    _write_prompt_table(prompts, stdout, style, stats_by_name)
    return 0


def cmd_find(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    formatter = PromptFormatter(ConsoleStyle(args.color, stdout))
    project_id, project_filter, _ = _project_selection(args, store)
    prompts = store.list(
        tags=_split_tags(args.tag),
        query=args.query,
        project_id=project_id,
        project_filter=project_filter,
    )
    _write_prompt_rows(prompts, stdout, formatter)
    return 0


def cmd_rm(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    if not args.yes:
        raise CliError("refusing to remove without --yes")
    store = _store(args)
    store.remove(args.name)
    _reporter(args, stderr).warning(f"Removed {args.name}")
    return 0


def cmd_tags(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    style = ConsoleStyle(args.color, stdout)
    project_id, project_filter, _ = _project_selection(args, store)
    for tag in store.tags(project_id=project_id, project_filter=project_filter):
        stdout.write(f"{style.paint('#' + tag.name, 'cyan')}\t{tag.prompt_count}\n")
    return 0


def cmd_tag_add(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    store.add_tags(args.name, args.tags)
    _reporter(args, stderr).success(f"Tagged {args.name}: {', '.join(args.tags)}")
    return 0


def cmd_tag_rm(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    store.remove_tags(args.name, args.tags)
    _reporter(args, stderr).warning(f"Removed tags from {args.name}: {', '.join(args.tags)}")
    return 0


def cmd_stats(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    style = ConsoleStyle(args.color, stdout)
    project_id, project_filter, _ = _project_selection(args, store)
    rows = store.stats(args.name, project_id=project_id, project_filter=project_filter)
    stdout.write(
        f"{style.paint('prompt', 'bold')}\tshows\tedits\tfeedback\tlast used\n"
    )
    for row in rows:
        stdout.write(
            f"{style.paint(row.name, 'magenta')}\t"
            f"{row.show_count}\t{row.edit_count}\t{row.feedback_count}\t"
            f"{row.last_used_at or '-'}\n"
        )
    return 0


def cmd_usage(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    style = ConsoleStyle(args.color, stdout)
    project_id, project_filter, _ = _project_selection(args, store)
    stdout.write(f"{style.paint('when', 'bold')}\taction\tprompts\tdetail\n")
    for event in store.usage(
        args.name,
        limit=args.limit,
        project_id=project_id,
        project_filter=project_filter,
    ):
        prompts = ", ".join(event.prompt_names) or "-"
        stdout.write(
            f"{event.used_at}\t"
            f"{style.paint(event.action, 'magenta')}\t"
            f"{prompts}\t"
            f"{event.detail or '-'}\n"
        )
    return 0


def cmd_versions(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    if args.show is not None:
        version = store.get_version(args.name, args.show)
        stdout.write(version.body)
        return 0

    if args.prune:
        if not args.yes:
            raise CliError("refusing to prune versions without --yes")
        deleted = store.prune_versions(args.name)
        _reporter(args, stderr).warning(f"Removed {deleted} previous versions for {args.name}")
        return 0

    style = ConsoleStyle(args.color, stdout)
    formatter = PromptFormatter(style)
    for version in store.versions(args.name):
        stdout.write(
            f"{style.paint(str(version.id), 'yellow')}\t"
            f"{version.created_at}\t{version.reason}\t{formatter.preview(version.body)}\n"
        )
    return 0


def cmd_feedback(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    if args.list:
        style = ConsoleStyle(args.color, stdout)
        formatter = PromptFormatter(style)
        for item in store.feedback(args.name):
            stdout.write(
                f"{style.paint(str(item.id), 'yellow')}\t"
                f"{item.created_at}\t{formatter.preview(item.body, 120)}\n"
            )
        return 0

    body = TextEditor.from_environment().read_or_edit(stdin)
    store.add_feedback(args.name, body)
    _reporter(args, stderr).success(f"Saved feedback for {args.name}")
    return 0


def cmd_browse(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    project_id, project_filter, _ = _project_selection(args, store)
    browser = InteractiveBrowser(
        store,
        TextEditor.from_environment(),
        stdin,
        stdout,
        color=args.color,
        initial_query=args.query,
        initial_tags=tuple(_split_tags(args.tag)),
        project_id=project_id,
        project_filter=project_filter,
    )
    return browser.run()


def cmd_project_init(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    context = ProjectResolver().initialize(Path(args.path) if args.path else None)
    _reporter(args, stderr).success(f"Initialized project prompt store at {context.database_path}")
    return 0


def cmd_project_status(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    context = _context(args)
    store = PromptStore(context.database_path)
    stdout.write(f"scope\t{context.scope}\n")
    stdout.write(f"database\t{context.database_path}\n")
    if context.project_root is not None:
        stdout.write(f"project\t{context.project_root}\n")
    active = store.active_project()
    if active is not None:
        stdout.write(f"active_project\t{active.name}\n")
    return 0


def cmd_project_create(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    description = args.description or _optional_words(args.description_text) or ""
    try:
        project = store.create_project(args.name, description)
    except ProjectExistsError as exc:
        raise CliError(f"project already exists: {exc.args[0]}") from exc
    _reporter(args, stderr).success(f"Created project {project.name}")
    return 0


def cmd_project_list(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    active = store.active_project()
    active_id = active.id if active else None
    stdout.write("project\tprompts\tnotes\tdescription\n")
    for project in store.projects():
        prompts = store.list(project_id=project.id, project_filter=True)
        notes = store.notes(project_id=project.id, project_filter=True)
        marker = "*" if project.id == active_id else " "
        stdout.write(f"{marker}{project.name}\t{len(prompts)}\t{len(notes)}\t{project.description}\n")
    return 0


def cmd_project_show(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    project = store.get_project(args.name)
    prompts = store.list(project_id=project.id, project_filter=True)
    notes = store.notes(project_id=project.id, project_filter=True)
    stdout.write(f"name\t{project.name}\n")
    stdout.write(f"description\t{project.description or '-'}\n")
    stdout.write(f"created\t{project.created_at}\n")
    stdout.write(f"updated\t{project.updated_at}\n")
    stdout.write(f"prompts\t{len(prompts)}\n")
    for prompt in prompts:
        stdout.write(f"  {prompt.name}\n")
    stdout.write(f"notes\t{len(notes)}\n")
    for note in notes:
        title = note.title or f"note {note.id}"
        stdout.write(f"  {note.id}\t{title}\n")
    return 0


def cmd_project_rename(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    try:
        project = store.rename_project(args.old, args.new)
    except ProjectExistsError as exc:
        raise CliError(f"project already exists: {exc.args[0]}") from exc
    _reporter(args, stderr).success(f"Renamed project {args.old} to {project.name}")
    return 0


def cmd_project_describe(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    description = _project_description_arg(args.text)
    project = _store(args).describe_project(args.name, description)
    _reporter(args, stderr).success(f"Updated project {project.name}")
    return 0


def cmd_project_edit(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    project = store.get_project(args.name)
    edited = TextEditor.from_environment().edit(_project_form(project.name, project.description))
    name, description = _parse_project_form(edited, project.name, project.description)
    try:
        updated = store.update_project(project.name, new_name=name, description=description)
    except ProjectExistsError as exc:
        raise CliError(f"project already exists: {exc.args[0]}") from exc
    _reporter(args, stderr).success(f"Updated project {updated.name}")
    return 0


def cmd_project_use(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    project = _store(args).use_project(args.name)
    _reporter(args, stderr).success(f"Using project {project.name}")
    return 0


def cmd_project_clear(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    _store(args).clear_active_project()
    _reporter(args, stderr).success("Cleared active project")
    return 0


def cmd_project_assign(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    _store(args).assign_project(args.project, args.prompts)
    _reporter(args, stderr).success(f"Assigned {len(args.prompts)} prompt(s) to {args.project}")
    return 0


def cmd_project_unassign(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    _store(args).unassign_project(args.prompts)
    _reporter(args, stderr).success(f"Unassigned {len(args.prompts)} prompt(s)")
    return 0


def cmd_note_add(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    project_id = store.project_id(args.project) if args.project else None
    title = args.title or _optional_words(args.title_text)
    body = TextEditor.from_environment().read_or_edit(stdin)
    note = store.add_note(body, title=title, project_id=project_id)
    target = f" in project {args.project}" if args.project else ""
    _reporter(args, stderr).success(f"Saved note {note.id}{target}")
    return 0


def cmd_note_list(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    project_id, project_filter, _ = _project_selection(args, store, use_active=False)
    stdout.write("id\tproject\ttitle\tupdated\n")
    for note in store.notes(project_id=project_id, project_filter=project_filter):
        stdout.write(
            f"{note.id}\t"
            f"{note.project_name or '-'}\t"
            f"{note.title or '-'}\t"
            f"{_short_timestamp(note.updated_at)}\n"
        )
    return 0


def cmd_note_show(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    note = _store(args).get_note(args.id)
    stdout.write(f"id\t{note.id}\n")
    stdout.write(f"project\t{note.project_name or '-'}\n")
    stdout.write(f"title\t{note.title or '-'}\n")
    stdout.write(f"created\t{note.created_at}\n")
    stdout.write(f"updated\t{note.updated_at}\n\n")
    stdout.write(note.body)
    if not note.body.endswith("\n"):
        stdout.write("\n")
    return 0


def cmd_note_edit(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    note = store.get_note(args.id)
    edited = TextEditor.from_environment().edit(_note_form(note.title, note.body))
    title, body = _parse_note_form(edited, note.title)
    store.update_note(note.id, body, title=title)
    _reporter(args, stderr).success(f"Updated note {note.id}")
    return 0


def cmd_note_versions(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    style = ConsoleStyle(args.color, stdout)
    formatter = PromptFormatter(style)
    for version in store.note_versions(args.id):
        title = version.title or "-"
        stdout.write(
            f"{style.paint(str(version.id), 'yellow')}\t"
            f"{version.created_at}\t{title}\t{formatter.preview(version.body)}\n"
        )
    return 0


def _md_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


EXPORT_INCLUDE_NAMES = frozenset({"usage", "versions", "comments", "notes"})


def _export_includes(raw: str | None) -> set[str]:
    if raw is None:
        return set(EXPORT_INCLUDE_NAMES)
    includes = {part.strip().lower() for part in raw.split(",") if part.strip()}
    unknown = includes - EXPORT_INCLUDE_NAMES
    if unknown:
        raise CliError(f"unknown export include: {', '.join(sorted(unknown))}")
    return includes


def _is_since(value: str, since: str | None) -> bool:
    return since is None or value >= since


def _export_scope(args: argparse.Namespace, store: PromptStore) -> tuple[int | None, bool, str | None]:
    if args.all:
        return None, False, None
    return _project_selection(args, store)


def _collect_export_data(
    store: PromptStore,
    *,
    project_id: int | None,
    project_filter: bool,
    project_name: str | None,
    includes: set[str],
    since: str | None,
) -> dict[str, Any]:
    prompts = sorted(
        store.list(project_id=project_id, project_filter=project_filter),
        key=lambda item: item.name.casefold(),
    )
    notes = []
    if "notes" in includes:
        notes = [
            note
            for note in store.notes(project_id=project_id, project_filter=project_filter)
            if _is_since(note.updated_at, since)
        ]
    projects = [store.get_project(project_name)] if project_name else store.projects()
    if project_filter and project_id is None:
        projects = []

    comments_by_prompt = {prompt.name: [] for prompt in prompts}
    if "comments" in includes:
        comments_by_prompt = {
            prompt.name: [
                item
                for item in sorted(store.feedback(prompt.name), key=lambda item: (item.created_at, item.id))
                if _is_since(item.created_at, since)
            ]
            for prompt in prompts
        }

    versions_by_prompt = {prompt.name: [] for prompt in prompts}
    note_versions_by_id = {note.id: [] for note in notes}
    if "versions" in includes:
        versions_by_prompt = {
            prompt.name: [
                version
                for version in sorted(store.versions(prompt.name), key=lambda item: (item.created_at, item.id))
                if _is_since(version.created_at, since)
            ]
            for prompt in prompts
        }
        note_versions_by_id = {
            note.id: [
                version
                for version in sorted(store.note_versions(note.id), key=lambda item: (item.created_at, item.id))
                if _is_since(version.created_at, since)
            ]
            for note in notes
        }

    usage = []
    if "usage" in includes:
        usage = [
            event
            for event in store.usage(
                limit=100000,
                project_id=project_id,
                project_filter=project_filter,
            )
            if _is_since(event.used_at, since)
        ]

    version_count = sum(len(items) for items in versions_by_prompt.values())
    version_count += sum(len(items) for items in note_versions_by_id.values())
    return {
        "projects": sorted(projects, key=lambda item: item.name.casefold()),
        "prompts": prompts,
        "notes": notes,
        "comments_by_prompt": comments_by_prompt,
        "versions_by_prompt": versions_by_prompt,
        "note_versions_by_id": note_versions_by_id,
        "usage": sorted(usage, key=lambda item: (item.used_at, item.id)),
        "index": {
            "projects": len(projects),
            "prompts": len(prompts),
            "notes": len(notes),
            "comments": sum(len(items) for items in comments_by_prompt.values()),
            "versions": version_count,
            "usage": len(usage),
        },
    }


def _write_markdown_export(
    store: PromptStore,
    stdout: TextIO,
    *,
    project_id: int | None,
    project_filter: bool,
    project_name: str | None,
    includes: set[str],
    since: str | None,
) -> None:
    data = _collect_export_data(
        store,
        project_id=project_id,
        project_filter=project_filter,
        project_name=project_name,
        includes=includes,
        since=since,
    )
    prompts = data["prompts"]
    notes = data["notes"]
    projects = data["projects"]
    comments_by_prompt = data["comments_by_prompt"]
    versions_by_prompt = data["versions_by_prompt"]
    note_versions_by_id = data["note_versions_by_id"]
    usage = data["usage"]

    stdout.write("# Prompt Deck Export\n\n")
    stdout.write("## Metadata\n\n")
    stdout.write(f"- database: `{store.path}`\n")
    if project_filter:
        stdout.write(f"- project: {project_name or 'unbound'}\n")
    else:
        stdout.write("- project: all\n")
    stdout.write(f"- include: {', '.join(sorted(includes)) or '-'}\n")
    if since:
        stdout.write(f"- since: {since}\n")
    stdout.write("\n")

    stdout.write("## Index\n\n")
    index = data["index"]
    stdout.write(
        f"- projects: {index['projects']}; prompts: {index['prompts']}; "
        f"notes: {index['notes']}; comments: {index['comments']}; "
        f"versions: {index['versions']}; usage: {index['usage']}\n\n"
    )
    if prompts:
        stdout.write("| prompt | project | tags | updated |\n")
        stdout.write("| --- | --- | --- | --- |\n")
        for prompt in prompts:
            stdout.write(
                f"| {_md_escape(prompt.name)} | {_md_escape(prompt.project_name or 'unbound')} | "
                f"{_md_escape(', '.join(prompt.tags) or '-')} | {_md_escape(prompt.updated_at)} |\n"
            )
        stdout.write("\n")
    stdout.write("\n")

    stdout.write("## Projects\n\n")
    if projects:
        for project in sorted(projects, key=lambda item: item.name.casefold()):
            stdout.write(f"### {project.name}\n\n")
            stdout.write(f"- id: {project.id}\n")
            stdout.write(f"- description: {project.description or '-'}\n")
            stdout.write(f"- created_at: {project.created_at}\n")
            stdout.write(f"- updated_at: {project.updated_at}\n\n")
    else:
        stdout.write("_No projects in scope._\n\n")

    stdout.write("## Prompts\n\n")
    if not prompts:
        stdout.write("_No prompts in scope._\n\n")
    for prompt in sorted(prompts, key=lambda item: item.name.casefold()):
        stdout.write(f"### {prompt.name}\n\n")
        stdout.write(f"- project: {prompt.project_name or 'unbound'}\n")
        stdout.write(f"- tags: {', '.join(prompt.tags) or '-'}\n")
        stdout.write(f"- created_at: {prompt.created_at}\n")
        stdout.write(f"- updated_at: {prompt.updated_at}\n\n")
        stdout.write("```text\n")
        stdout.write(prompt.body)
        if not prompt.body.endswith("\n"):
            stdout.write("\n")
        stdout.write("```\n\n")

        if "comments" in includes:
            feedback_items = comments_by_prompt[prompt.name]
            stdout.write("#### Comments\n\n")
            if feedback_items:
                for item in feedback_items:
                    stdout.write(f"- {item.created_at} [{item.id}]: {_md_escape(item.body)}\n")
            else:
                stdout.write("_No comments._\n")
            stdout.write("\n")

        if "versions" in includes:
            versions = versions_by_prompt[prompt.name]
            stdout.write("#### Versions\n\n")
            if versions:
                for version in versions:
                    stdout.write(f"- {version.created_at} [{version.id}] {version.reason}\n\n")
                    stdout.write("```text\n")
                    stdout.write(version.body)
                    if not version.body.endswith("\n"):
                        stdout.write("\n")
                    stdout.write("```\n\n")
            else:
                stdout.write("_No previous versions._\n\n")

    if "notes" in includes:
        stdout.write("## Notes\n\n")
        if not notes:
            stdout.write("_No notes in scope._\n\n")
        for note in notes:
            stdout.write(f"### {note.title or 'Untitled note'} [{note.id}]\n\n")
            stdout.write(f"- project: {note.project_name or 'unbound'}\n")
            stdout.write(f"- created_at: {note.created_at}\n")
            stdout.write(f"- updated_at: {note.updated_at}\n\n")
            stdout.write("```text\n")
            stdout.write(note.body)
            if not note.body.endswith("\n"):
                stdout.write("\n")
            stdout.write("```\n\n")
            if "versions" in includes:
                versions = note_versions_by_id[note.id]
                stdout.write("#### Note Versions\n\n")
                if versions:
                    for version in versions:
                        stdout.write(f"- {version.created_at} [{version.id}] {version.title or '-'}\n\n")
                        stdout.write("```text\n")
                        stdout.write(version.body)
                        if not version.body.endswith("\n"):
                            stdout.write("\n")
                        stdout.write("```\n\n")
                else:
                    stdout.write("_No previous versions._\n\n")

    if "usage" in includes:
        stdout.write("## Usage Timeline\n\n")
        if usage:
            stdout.write("| when | action | prompts | detail |\n")
            stdout.write("| --- | --- | --- | --- |\n")
            for event in usage:
                stdout.write(
                    f"| {_md_escape(event.used_at)} | {_md_escape(str(event.action))} | "
                    f"{_md_escape(', '.join(event.prompt_names) or '-')} | "
                    f"{_md_escape(event.detail or '-')} |\n"
                )
        else:
            stdout.write("_No usage in scope._\n")


def _write_json_export(
    store: PromptStore,
    stdout: TextIO,
    *,
    project_id: int | None,
    project_filter: bool,
    project_name: str | None,
    includes: set[str],
    since: str | None,
) -> None:
    data = _collect_export_data(
        store,
        project_id=project_id,
        project_filter=project_filter,
        project_name=project_name,
        includes=includes,
        since=since,
    )
    prompts = []
    for prompt in data["prompts"]:
        item = prompt.model_dump(mode="json")
        if "comments" in includes:
            item["comments"] = [
                comment.model_dump(mode="json")
                for comment in data["comments_by_prompt"][prompt.name]
            ]
        if "versions" in includes:
            item["versions"] = [
                version.model_dump(mode="json")
                for version in data["versions_by_prompt"][prompt.name]
            ]
        prompts.append(item)

    notes = []
    if "notes" in includes:
        for note in data["notes"]:
            item = note.model_dump(mode="json")
            if "versions" in includes:
                item["versions"] = [
                    version.model_dump(mode="json")
                    for version in data["note_versions_by_id"][note.id]
                ]
            notes.append(item)

    payload = {
        "metadata": {
            "database": str(store.path),
            "project": project_name if project_filter else "all",
            "unbound": project_filter and project_id is None,
            "include": sorted(includes),
            "since": since,
        },
        "index": data["index"],
        "projects": [project.model_dump(mode="json") for project in data["projects"]],
        "prompts": prompts,
        "notes": notes,
        "usage": [
            event.model_dump(mode="json")
            for event in data["usage"]
        ] if "usage" in includes else [],
    }
    json.dump(payload, stdout, indent=2)
    stdout.write("\n")


def cmd_export(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    project_id, project_filter, project_name = _export_scope(args, store)
    includes = _export_includes(args.include)
    writer = _write_json_export if args.format == "json" else _write_markdown_export
    if args.output:
        with Path(args.output).expanduser().open("w", encoding="utf-8") as file:
            writer(
                store,
                file,
                project_id=project_id,
                project_filter=project_filter,
                project_name=project_name,
                includes=includes,
                since=args.since,
            )
        _reporter(args, stderr).success(f"Exported {args.output}")
        return 0
    writer(
        store,
        stdout,
        project_id=project_id,
        project_filter=project_filter,
        project_name=project_name,
        includes=includes,
        since=args.since,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdk",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Prompt Deck keeps reusable prompts, notes, comments, and history close to your shell.\n"
            "Use it as a small context library: save prompts, group them into named projects,\n"
            "and export the active context as Markdown when an AI needs the whole picture."
        ),
        epilog="""
Use cases:
  Save a prompt from stdin:
    pdk add review --tag work < review.md

  Print a prompt cleanly for a pipe:
    pdk show review | pbcopy

  Work inside the nearest .pdk store instead of the global store:
    pdk project init
    pdk add repo-review < prompt.md

  Group prompts inside the current store:
    pdk project create client-a "Client A launch"
    pdk project use client-a
    pdk add launch-review < review.md
    pdk project edit client-a

  Keep notes beside prompts:
    pdk note add "Decision log"
    pdk note add "Launch facts" --project client-a

  Export context for an AI:
    pdk context client-a > context.md
    pdk context client-a | pbcopy
    pdk context --all > full-context.md

How scope and projects fit together:
  --scope chooses the database first. In auto mode, pdk uses .pdk/prompts.sqlite3
  when you are inside an initialized folder; otherwise it uses the global store.
  Named projects live inside that selected database. Use --project for one command,
  --no-project for unbound prompts/notes, and `pdk project clear` to stop filtering
  by the active named project.

Examples:
  pdk context client-a > context.md
  pdk browse --query review

Run `pdk COMMAND --help` for command-specific examples.
""",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="colorize UI output",
    )
    parser.add_argument(
        "--scope",
        choices=("auto", "global", "project"),
        default="auto",
        help="choose prompt store; auto uses .pdk when present",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser(
        "add",
        help="save a prompt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Save a prompt body from stdin, or open $EDITOR when stdin is empty.",
        epilog="""
Examples:
  pdk add review < review.md
  pbpaste | pdk add rewrite --tag writing
  pdk add review --replace < better-review.md
  pdk add launch-review --project client-a < review.md
  pdk add shared-template --no-project < template.md

Project behavior:
  If a named project is active, `pdk add NAME` saves into it.
  Use --project for a one-command override, or --no-project for a shared prompt.
""",
    )
    add.add_argument("name")
    add.add_argument("--replace", action="store_true", help="replace an existing prompt")
    add.add_argument("--tag", action="append", help="attach a tag; repeat or use comma-separated tags")
    add.add_argument("--project", help="assign the prompt to a named project")
    add.add_argument("--no-project", action="store_true", help="save as an unbound prompt")
    add.set_defaults(func=cmd_add)

    edit = subparsers.add_parser("edit", help="edit an existing prompt")
    edit.add_argument("name")
    edit.set_defaults(func=cmd_edit)

    show = subparsers.add_parser("show", help="print a prompt")
    show.add_argument("name")
    show.set_defaults(func=cmd_show)

    list_cmd = subparsers.add_parser(
        "list",
        help="scan saved prompts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Show an inventory table with use counts, edit counts, comments, last use, and tags.",
        epilog="""
Examples:
  pdk list
  pdk list --tag work
  pdk list --query review
  pdk list --project client-a
  pdk list --no-project

Tip:
  `list` is for scanning names and metadata. Use `find QUERY` when you want body
  text to participate in search results.
""",
    )
    list_cmd.add_argument("--tag", action="append", help="filter by tag; repeat for all required tags")
    list_cmd.add_argument("--query", help="filter by name, body, or tag text")
    list_cmd.add_argument("--project", help="filter by named project")
    list_cmd.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    list_cmd.set_defaults(func=cmd_list)

    find = subparsers.add_parser(
        "find",
        help="search prompt names, bodies, and tags",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Search prompt names, bodies, and tags, then print compact matching rows.",
        epilog="""
Examples:
  pdk find essay
  pdk find review --tag work
  pdk find launch --project client-a
""",
    )
    find.add_argument("query")
    find.add_argument("--tag", action="append", help="filter by tag; repeat for all required tags")
    find.add_argument("--project", help="filter by named project")
    find.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    find.set_defaults(func=cmd_find)

    tags = subparsers.add_parser("tags", help="show tag aggregation")
    tags.add_argument("--project", help="filter by named project")
    tags.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    tags.set_defaults(func=cmd_tags)

    tag = subparsers.add_parser("tag", help="add or remove tags")
    tag_subparsers = tag.add_subparsers(dest="tag_command", required=True)
    tag_add = tag_subparsers.add_parser("add", help="add tags to a prompt")
    tag_add.add_argument("name")
    tag_add.add_argument("tags", nargs="+")
    tag_add.set_defaults(func=cmd_tag_add)
    tag_rm = tag_subparsers.add_parser("rm", help="remove tags from a prompt")
    tag_rm.add_argument("name")
    tag_rm.add_argument("tags", nargs="+")
    tag_rm.set_defaults(func=cmd_tag_rm)

    stats = subparsers.add_parser("stats", help="show prompt usage statistics")
    stats.add_argument("name", nargs="?")
    stats.add_argument("--project", help="filter by named project")
    stats.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    stats.set_defaults(func=cmd_stats)

    usage = subparsers.add_parser("usage", help="show detailed usage events")
    usage.add_argument("name", nargs="?")
    usage.add_argument("--limit", type=int, default=50)
    usage.add_argument("--project", help="filter by named project")
    usage.add_argument("--no-project", action="store_true", help="filter unbound prompt usage")
    usage.set_defaults(func=cmd_usage)

    versions = subparsers.add_parser("versions", help="inspect or clean previous prompt versions")
    versions.add_argument("name")
    versions.add_argument("--show", type=int, metavar="ID", help="print a previous version")
    versions.add_argument("--prune", action="store_true", help="delete previous versions")
    versions.add_argument("--yes", action="store_true", help="confirm pruning")
    versions.set_defaults(func=cmd_versions)

    feedback = subparsers.add_parser(
        "feedback",
        help="attach or list comments for a prompt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Save comments, observations, or evaluation notes against one prompt.",
        epilog="""
Examples:
  pdk feedback review < feedback.md
  pdk feedback review --list

Alias:
  pdk comment review < comment.md
""",
    )
    feedback.add_argument("name")
    feedback.add_argument("--list", action="store_true", help="list existing feedback")
    feedback.set_defaults(func=cmd_feedback)
    comment = subparsers.add_parser("comment", help="alias for feedback")
    comment.add_argument("name")
    comment.add_argument("--list", action="store_true", help="list existing comments")
    comment.set_defaults(func=cmd_feedback)

    browse = subparsers.add_parser(
        "browse",
        help="browse, print, copy, edit, and comment interactively",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Open an interactive prompt browser with search, tag filters, editing, comments, and versions.",
        epilog="""
Examples:
  pdk browse
  pdk browse --query review
  pdk browse --tag work
  pdk browse --project client-a
""",
    )
    browse.add_argument("--tag", action="append", help="start with a tag filter")
    browse.add_argument("--query", help="start with a text search")
    browse.add_argument("--project", help="filter by named project")
    browse.add_argument("--no-project", action="store_true", help="filter unbound prompts")
    browse.set_defaults(func=cmd_browse)

    project = subparsers.add_parser(
        "project",
        help="initialize .pdk stores and manage named projects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Project has two jobs: initialize filesystem-local .pdk stores, and manage\n"
            "named projects inside whichever database --scope selects."
        ),
        epilog="""
Use cases:
  Create a .pdk database in this repo:
    pdk project init

  See which database pdk is using:
    pdk project status

  Create and activate a named project in the selected database:
    pdk project create client-a "Client A launch"
    pdk project use client-a
    pdk project edit client-a

  Move existing prompts in or out of a named project:
    pdk project assign client-a review rewrite
    pdk project unassign review

  Stop filtering normal commands by the active named project:
    pdk project clear
""",
    )
    project_subparsers = project.add_subparsers(dest="project_command", required=True)
    project_create = project_subparsers.add_parser("create", help="create a named project")
    project_create.add_argument("name")
    project_create.add_argument("description_text", nargs="*", help="optional project description")
    project_create.add_argument("--description", help="project description")
    project_create.set_defaults(func=cmd_project_create)
    project_list = project_subparsers.add_parser("list", help="list named projects")
    project_list.set_defaults(func=cmd_project_list)
    project_show = project_subparsers.add_parser("show", help="show a named project")
    project_show.add_argument("name")
    project_show.set_defaults(func=cmd_project_show)
    project_rename = project_subparsers.add_parser("rename", help="rename a named project")
    project_rename.add_argument("old")
    project_rename.add_argument("new")
    project_rename.set_defaults(func=cmd_project_rename)
    project_describe = project_subparsers.add_parser("describe", help="replace a project description")
    project_describe.add_argument("name")
    project_describe.add_argument("text", nargs="+")
    project_describe.set_defaults(func=cmd_project_describe)
    project_edit = project_subparsers.add_parser("edit", help="edit project name and description")
    project_edit.add_argument("name")
    project_edit.set_defaults(func=cmd_project_edit)
    project_use = project_subparsers.add_parser("use", help="make a named project active")
    project_use.add_argument("name")
    project_use.set_defaults(func=cmd_project_use)
    project_clear = project_subparsers.add_parser("clear", help="clear the active named project")
    project_clear.set_defaults(func=cmd_project_clear)
    project_assign = project_subparsers.add_parser("assign", help="assign prompts to a project")
    project_assign.add_argument("project")
    project_assign.add_argument("prompts", nargs="+")
    project_assign.set_defaults(func=cmd_project_assign)
    project_unassign = project_subparsers.add_parser("unassign", help="remove prompts from named projects")
    project_unassign.add_argument("prompts", nargs="+")
    project_unassign.set_defaults(func=cmd_project_unassign)
    project_init = project_subparsers.add_parser("init", help="initialize .pdk in a folder")
    project_init.add_argument("path", nargs="?", help="project folder; defaults to cwd")
    project_init.set_defaults(func=cmd_project_init)
    project_status = project_subparsers.add_parser("status", help="show active prompt store")
    project_status.set_defaults(func=cmd_project_status)

    note = subparsers.add_parser(
        "note",
        help="save and edit context notes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Notes are free-form context. They are unbound by default, even when a named project is active.",
        epilog="""
Examples:
  pdk note add "Decision log"
  pdk note add "Launch facts" --project client-a
  pdk note list
  pdk note list --no-project
  pdk note show 1
  pdk note edit 1
  pdk note versions 1
""",
    )
    note_subparsers = note.add_subparsers(dest="note_command", required=True)
    note_add = note_subparsers.add_parser("add", help="add a note")
    note_add.add_argument("title_text", nargs="*", help="note title")
    note_add.add_argument("--title", help="note title")
    note_add.add_argument("--project", help="bind the note to a named project")
    note_add.set_defaults(func=cmd_note_add)
    note_list = note_subparsers.add_parser("list", help="list notes")
    note_list.add_argument("--project", help="filter by named project")
    note_list.add_argument("--no-project", action="store_true", help="filter unbound notes")
    note_list.set_defaults(func=cmd_note_list)
    note_show = note_subparsers.add_parser("show", help="show a note")
    note_show.add_argument("id", type=int)
    note_show.set_defaults(func=cmd_note_show)
    note_edit = note_subparsers.add_parser("edit", help="edit a note title and body")
    note_edit.add_argument("id", type=int)
    note_edit.set_defaults(func=cmd_note_edit)
    note_versions = note_subparsers.add_parser("versions", help="show note versions")
    note_versions.add_argument("id", type=int)
    note_versions.set_defaults(func=cmd_note_versions)

    export = subparsers.add_parser(
        "export",
        help="write the current context as Markdown",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Export prompts, notes, comments, prompt versions, note versions, and usage history.\n"
            "By default this exports the active named project when one is set; otherwise it exports the whole store."
        ),
        epilog="""
Examples:
  pdk export
  pdk context > context.md
  pdk context client-a > context.md
  pdk export --project client-a --output context.md
  pdk export --include usage,versions,comments,notes --since 2026-01-01
  pdk export --format json
  pdk export --all
  pdk export --no-project
""",
    )
    export.add_argument("--project", help="export a named project")
    export.add_argument("--all", action="store_true", help="export the entire current store")
    export.add_argument("--no-project", action="store_true", help="export unbound prompts and notes")
    export.add_argument("--include", help="comma-separated sections: usage,versions,comments,notes")
    export.add_argument("--since", help="include dated history from DATE or ISO timestamp")
    export.add_argument("--format", choices=("markdown", "json"), default="markdown", help="export format")
    export.add_argument("--output", help="write Markdown to a file")
    export.set_defaults(func=cmd_export)

    context = subparsers.add_parser(
        "context",
        help="write the current AI context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Alias for export, named for the common use-case: gather active AI context.",
        epilog="""
Examples:
  pdk context > context.md
  pdk context thesis | pbcopy
  pdk context --include notes,comments
""",
    )
    context.add_argument("project_name", nargs="?", help="named project to export")
    context.add_argument("--project", help="export a named project")
    context.add_argument("--all", action="store_true", help="export the entire current store")
    context.add_argument("--no-project", action="store_true", help="export unbound prompts and notes")
    context.add_argument("--include", help="comma-separated sections: usage,versions,comments,notes")
    context.add_argument("--since", help="include dated history from DATE or ISO timestamp")
    context.add_argument("--format", choices=("markdown", "json"), default="markdown", help="export format")
    context.add_argument("--output", help="write context to a file")
    context.set_defaults(func=cmd_export)

    rm = subparsers.add_parser("rm", help="remove a prompt")
    rm.add_argument("name")
    rm.add_argument("--yes", action="store_true", help="confirm removal")
    rm.set_defaults(func=cmd_rm)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return args.func(args, sys.stdin, sys.stdout, sys.stderr)
    except (
        CliError,
        NamedProjectNotFoundError,
        NoteNotFoundError,
        PromptNotFoundError,
        ProjectNotFoundError,
        EditorError,
        VariableFillCancelled,
        ValidationError,
    ) as exc:
        if isinstance(exc, PromptNotFoundError):
            message = f"prompt not found: {exc.args[0]}"
        elif isinstance(exc, NamedProjectNotFoundError):
            message = f"project not found: {exc.args[0]}"
        elif isinstance(exc, NoteNotFoundError):
            message = f"note not found: {exc.args[0]}"
        elif isinstance(exc, ValidationError):
            message = exc.errors()[0]["msg"]
        else:
            message = str(exc)
        _reporter(args, sys.stderr).error(message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
