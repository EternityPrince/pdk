from __future__ import annotations

import argparse
from pathlib import Path
from typing import TextIO

from .command_support import (
    CliError,
    _context,
    _note_form,
    _optional_words,
    _parse_note_form,
    _parse_project_form,
    _project_description_arg,
    _project_form,
    _project_selection,
    _reporter,
    _short_timestamp,
    _store,
    _warn_secrets,
)
from .editor import TextEditor
from .project import ProjectResolver
from .store import ProjectExistsError, PromptStore
from .ui import ConsoleStyle, PromptFormatter


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
    _warn_secrets(args, stderr, title or "note", body)
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
            f"{note.id}\t{note.project_name or '-'}\t{note.title or '-'}\t{_short_timestamp(note.updated_at)}\n"
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
    _warn_secrets(args, stderr, title or f"note {note.id}", body)
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
