from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .command_support import CliError, _project_selection, _reporter, _store, _warn_secrets
from .models import UsageAction, VersionReason
from .security import redact_text, redact_value, secret_warnings
from .store import NamedProjectNotFoundError, PromptNotFoundError, PromptStore


EXPORT_INCLUDE_NAMES = frozenset({"usage", "versions", "comments", "notes"})


_HEADING_RE = re.compile(r"^(#{2,4}) (.+)$")
_FENCE_RE = re.compile(r"^```")
_NOTE_TITLE_RE = re.compile(r"^(?P<title>.+) \[(?P<id>\d+)\]$")


def _md_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


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
    redact: bool = False,
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
            description = redact_text(project.description) if redact else project.description
            stdout.write(f"- description: {description or '-'}\n")
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
        prompt_body = redact_text(prompt.body) if redact else prompt.body
        stdout.write(prompt_body)
        if not prompt_body.endswith("\n"):
            stdout.write("\n")
        stdout.write("```\n\n")

        if "comments" in includes:
            feedback_items = comments_by_prompt[prompt.name]
            stdout.write("#### Comments\n\n")
            if feedback_items:
                for item in feedback_items:
                    body = redact_text(item.body) if redact else item.body
                    stdout.write(f"- {item.created_at} [{item.id}]: {_md_escape(body)}\n")
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
                    version_body = redact_text(version.body) if redact else version.body
                    stdout.write(version_body)
                    if not version_body.endswith("\n"):
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
            note_body = redact_text(note.body) if redact else note.body
            stdout.write(note_body)
            if not note_body.endswith("\n"):
                stdout.write("\n")
            stdout.write("```\n\n")
            if "versions" in includes:
                versions = note_versions_by_id[note.id]
                stdout.write("#### Note Versions\n\n")
                if versions:
                    for version in versions:
                        stdout.write(f"- {version.created_at} [{version.id}] {version.title or '-'}\n\n")
                        stdout.write("```text\n")
                        version_body = redact_text(version.body) if redact else version.body
                        stdout.write(version_body)
                        if not version_body.endswith("\n"):
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
    redact: bool = False,
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
            item["comments"] = [comment.model_dump(mode="json") for comment in data["comments_by_prompt"][prompt.name]]
        if "versions" in includes:
            item["versions"] = [version.model_dump(mode="json") for version in data["versions_by_prompt"][prompt.name]]
        prompts.append(item)

    notes = []
    if "notes" in includes:
        for note in data["notes"]:
            item = note.model_dump(mode="json")
            if "versions" in includes:
                item["versions"] = [version.model_dump(mode="json") for version in data["note_versions_by_id"][note.id]]
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
        "usage": [event.model_dump(mode="json") for event in data["usage"]] if "usage" in includes else [],
    }
    if redact:
        payload = redact_value(payload)
    json.dump(payload, stdout, indent=2)
    stdout.write("\n")


def _warn_export_secrets(
    args: argparse.Namespace,
    store: PromptStore,
    stderr: TextIO,
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
    findings: set[str] = set()
    for project in data["projects"]:
        findings.update(secret_warnings(project.description))
    for prompt in data["prompts"]:
        findings.update(secret_warnings(prompt.body))
        for item in data["comments_by_prompt"].get(prompt.name, []):
            findings.update(secret_warnings(item.body))
        for version in data["versions_by_prompt"].get(prompt.name, []):
            findings.update(secret_warnings(version.body))
    for note in data["notes"]:
        findings.update(secret_warnings(note.body))
        for version in data["note_versions_by_id"].get(note.id, []):
            findings.update(secret_warnings(version.body))
    if findings:
        _reporter(args, stderr).warning(
            "export may contain secret-like data; use --redact to mask: " + ", ".join(sorted(findings))
        )


class ImportSummary:
    def __init__(self) -> None:
        self.projects = 0
        self.prompts = 0
        self.notes = 0
        self.comments = 0
        self.versions = 0
        self.usage = 0
        self.skipped = 0

    def line(self, *, dry_run: bool) -> str:
        verb = "Would import" if dry_run else "Imported"
        return (
            f"{verb} {self.projects} project(s), {self.prompts} prompt(s), "
            f"{self.notes} note(s), {self.comments} comment(s), "
            f"{self.versions} version(s), {self.usage} usage event(s); skipped {self.skipped}"
        )


def _read_import_text(args: argparse.Namespace, stdin: TextIO) -> str:
    if args.input:
        return Path(args.input).expanduser().read_text(encoding="utf-8")
    return stdin.read()


def _guess_import_format(args: argparse.Namespace, text: str) -> str:
    if args.format != "auto":
        return args.format
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return "json"
    if stripped.startswith("# Prompt Deck Export"):
        return "markdown"
    raise CliError("could not detect import format; pass --format json or --format markdown")


def _project_name_from_value(value: Any) -> str | None:
    if value in (None, "", "unbound", "-"):
        return None
    return str(value)


def _project_id_for_import(
    store: PromptStore,
    name: str | None,
    descriptions: dict[str, str],
    planned_projects: set[str],
    summary: ImportSummary,
    *,
    dry_run: bool,
) -> int | None:
    if name is None:
        return None
    if dry_run and name in planned_projects:
        return None
    try:
        return store.project_id(name)
    except NamedProjectNotFoundError:
        pass
    planned_projects.add(name)
    summary.projects += 1
    if dry_run:
        return None
    return store.create_project(name, descriptions.get(name, "")).id


def _prompt_exists(store: PromptStore, name: str) -> bool:
    try:
        store.get(name)
    except PromptNotFoundError:
        return False
    return True


def _note_exists(store: PromptStore, *, project_id: int | None, title: str | None, body: str) -> bool:
    for note in store.notes(project_id=project_id, project_filter=True):
        if note.title == title and note.body == body:
            return True
    return False


def _import_project_descriptions(payload: dict[str, Any]) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for item in payload.get("projects", []):
        if isinstance(item, dict) and item.get("name"):
            descriptions[str(item["name"])] = str(item.get("description") or "")
    return descriptions


def _import_prompt_versions(
    store: PromptStore,
    prompt_name: str,
    versions: Any,
    summary: ImportSummary,
    *,
    dry_run: bool,
) -> None:
    for version in versions or []:
        if not isinstance(version, dict) or version.get("body") is None:
            summary.skipped += 1
            continue
        try:
            reason = VersionReason(version.get("reason") or VersionReason.EDIT)
        except ValueError:
            summary.skipped += 1
            continue
        created_at = str(version.get("created_at") or datetime.now().isoformat())
        summary.versions += 1
        if not dry_run:
            store.import_prompt_version(prompt_name, str(version["body"]), reason, created_at)


def _import_note_versions(
    store: PromptStore,
    note_id: int,
    versions: Any,
    summary: ImportSummary,
    *,
    dry_run: bool,
) -> None:
    for version in versions or []:
        if not isinstance(version, dict) or version.get("body") is None:
            summary.skipped += 1
            continue
        created_at = str(version.get("created_at") or datetime.now().isoformat())
        title = version.get("title")
        summary.versions += 1
        if not dry_run:
            store.import_note_version(
                note_id,
                str(version["body"]),
                title=str(title) if title is not None else None,
                created_at=created_at,
            )


def _import_usage_events(
    store: PromptStore,
    events: Any,
    summary: ImportSummary,
    *,
    available_prompt_names: set[str],
    dry_run: bool,
) -> None:
    for event in events or []:
        if not isinstance(event, dict):
            summary.skipped += 1
            continue
        try:
            action = UsageAction(event.get("action") or "")
        except ValueError:
            summary.skipped += 1
            continue
        prompt_names = tuple(str(name) for name in event.get("prompt_names") or ())
        if any(name not in available_prompt_names and not _prompt_exists(store, name) for name in prompt_names):
            summary.skipped += 1
            continue
        used_at = str(event.get("used_at") or datetime.now().isoformat())
        detail = event.get("detail")
        summary.usage += 1
        if not dry_run:
            store.import_usage(
                action,
                prompt_names,
                detail=str(detail) if detail is not None else None,
                used_at=used_at,
            )


def _import_json_payload(
    store: PromptStore,
    payload: dict[str, Any],
    *,
    replace: bool,
    dry_run: bool,
) -> ImportSummary:
    descriptions = _import_project_descriptions(payload)
    summary = ImportSummary()
    planned_projects: set[str] = set()
    available_prompt_names = {prompt.name for prompt in store.list()}

    for name in sorted(descriptions):
        _project_id_for_import(store, name, descriptions, planned_projects, summary, dry_run=dry_run)

    for item in payload.get("prompts", []):
        if not isinstance(item, dict):
            summary.skipped += 1
            continue
        name = str(item.get("name") or "").strip()
        body = item.get("body")
        if not name or body is None:
            summary.skipped += 1
            continue
        project_name = _project_name_from_value(item.get("project_name"))
        project_id = _project_id_for_import(
            store,
            project_name,
            descriptions,
            planned_projects,
            summary,
            dry_run=dry_run,
        )
        exists = _prompt_exists(store, name)
        if exists and not replace:
            summary.skipped += 1
            continue
        summary.prompts += 1
        available_prompt_names.add(name)
        if not dry_run:
            now = datetime.now().isoformat()
            store.import_prompt(
                name,
                str(body),
                tags=item.get("tags") or (),
                project_id=project_id,
                created_at=str(item.get("created_at") or now),
                updated_at=str(item.get("updated_at") or now),
                replace=exists or replace,
            )
        _import_prompt_versions(store, name, item.get("versions"), summary, dry_run=dry_run)
        for comment in item.get("comments", []):
            if not isinstance(comment, dict) or comment.get("body") is None:
                summary.skipped += 1
                continue
            summary.comments += 1
            if not dry_run:
                store.import_feedback(
                    name,
                    str(comment["body"]),
                    str(comment.get("created_at") or datetime.now().isoformat()),
                )

    for item in payload.get("notes", []):
        if not isinstance(item, dict):
            summary.skipped += 1
            continue
        body = item.get("body")
        if body is None:
            summary.skipped += 1
            continue
        title = item.get("title")
        project_name = _project_name_from_value(item.get("project_name"))
        project_id = _project_id_for_import(
            store,
            project_name,
            descriptions,
            planned_projects,
            summary,
            dry_run=dry_run,
        )
        note_title = str(title) if title is not None else None
        note_body = str(body)
        if not dry_run and _note_exists(store, project_id=project_id, title=note_title, body=note_body):
            summary.skipped += 1
            continue
        summary.notes += 1
        imported_note_id: int | None = None
        if not dry_run:
            imported_note_id = store.add_note(note_body, title=note_title, project_id=project_id).id
        if dry_run:
            for version in item.get("versions") or []:
                if isinstance(version, dict) and version.get("body") is not None:
                    summary.versions += 1
                else:
                    summary.skipped += 1
        elif imported_note_id is not None:
            _import_note_versions(store, imported_note_id, item.get("versions"), summary, dry_run=False)

    _import_usage_events(
        store,
        payload.get("usage"),
        summary,
        available_prompt_names=available_prompt_names,
        dry_run=dry_run,
    )
    return summary


def _metadata_value(lines: list[str], key: str) -> str | None:
    prefix = f"- {key}: "
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _fenced_text(lines: list[str]) -> str:
    for index, line in enumerate(lines):
        if _FENCE_RE.match(line):
            body: list[str] = []
            for body_line in lines[index + 1 :]:
                if _FENCE_RE.match(body_line):
                    return "\n".join(body)
                body.append(body_line)
    return ""


def _parse_markdown_export(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "# Prompt Deck Export":
        raise CliError("markdown import expects a Prompt Deck export")

    projects: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    section: str | None = None
    current: tuple[str, str, list[str]] | None = None

    def finish() -> None:
        nonlocal current
        if current is None:
            return
        kind, title, body_lines = current
        if kind == "project":
            projects.append(
                {
                    "name": title,
                    "description": _metadata_value(body_lines, "description") or "",
                }
            )
        elif kind == "prompt":
            tags = _metadata_value(body_lines, "tags") or "-"
            prompts.append(
                {
                    "name": title,
                    "project_name": _project_name_from_value(_metadata_value(body_lines, "project")),
                    "tags": [] if tags == "-" else [part.strip() for part in tags.split(",")],
                    "body": _fenced_text(body_lines),
                }
            )
        elif kind == "note":
            match = _NOTE_TITLE_RE.match(title)
            note_title = match.group("title") if match else title
            if note_title == "Untitled note":
                note_title = None
            notes.append(
                {
                    "title": note_title,
                    "project_name": _project_name_from_value(_metadata_value(body_lines, "project")),
                    "body": _fenced_text(body_lines),
                }
            )
        current = None

    for line in lines[1:]:
        match = _HEADING_RE.match(line)
        if match:
            level, title = match.groups()
            if level == "##":
                finish()
                section = title
                continue
            if level == "###":
                finish()
                if section == "Projects":
                    current = ("project", title, [])
                elif section == "Prompts":
                    current = ("prompt", title, [])
                elif section == "Notes":
                    current = ("note", title, [])
                continue
            if level == "####":
                finish()
                current = None
                continue
        if current is not None:
            current[2].append(line)
    finish()
    return {"projects": projects, "prompts": prompts, "notes": notes}


def cmd_import(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    text = _read_import_text(args, stdin)
    if not text.strip():
        raise CliError("import input is empty")
    _warn_secrets(args, stderr, "import input", text)
    import_format = _guess_import_format(args, text)
    if import_format == "json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CliError(f"invalid JSON import: {exc}") from exc
        if not isinstance(payload, dict):
            raise CliError("JSON import must be an object")
    else:
        payload = _parse_markdown_export(text)

    summary = _import_json_payload(
        _store(args),
        payload,
        replace=args.replace,
        dry_run=args.dry_run,
    )
    _reporter(args, stderr).success(summary.line(dry_run=args.dry_run))
    return 0


def cmd_export(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    project_id, project_filter, project_name = _export_scope(args, store)
    includes = _export_includes(args.include)
    if not args.redact:
        _warn_export_secrets(
            args,
            store,
            stderr,
            project_id=project_id,
            project_filter=project_filter,
            project_name=project_name,
            includes=includes,
            since=args.since,
        )
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
                redact=args.redact,
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
        redact=args.redact,
    )
    return 0
