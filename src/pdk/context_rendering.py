from __future__ import annotations

import json

from .context_models import ContextDocument


def _md_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _module_targets(dirs: tuple[str, ...], files: tuple[str, ...]) -> str:
    targets = [*(f"dir:{value}" for value in dirs), *(f"file:{value}" for value in files)]
    return ", ".join(targets) if targets else "-"


def _append_module_map(lines: list[str], document: ContextDocument) -> None:
    if not document.modules:
        return
    lines.extend(["## Modules", ""])
    lines.extend(["| module | depends_on | targets | description |", "| --- | --- | --- | --- |"])
    for module in document.modules:
        lines.append(
            f"| {_md_escape(module.name)} | {_md_escape(', '.join(module.depends_on) or '-')} | "
            f"{_md_escape(_module_targets(module.dirs, module.files))} | "
            f"{_md_escape(module.description or '-')} |"
        )
    lines.append("")


def _append_file_body(lines: list[str], file) -> None:
    if file.detail == "full":
        lines.extend(["#### Full Text", "", "```text"])
        lines.append((file.text or "").rstrip("\n"))
        lines.extend(["```", ""])
    else:
        lines.extend(["#### Summary", "", "```text"])
        lines.append((file.summary or "").rstrip("\n"))
        lines.extend(["```", ""])


def _append_metadata(lines: list[str], document: ContextDocument) -> None:
    options = document.options
    lines.append(f"- database: `{options.database}`")
    if options.project_filter:
        lines.append(f"- project: {options.project_name or 'unbound'}")
    else:
        lines.append("- project: all")
    lines.append(f"- include: {', '.join(sorted(options.includes)) or '-'}")
    if options.compact:
        lines.append("- compact: true")
    if options.since:
        lines.append(f"- since: {options.since}")
    if options.budget is not None:
        lines.append(f"- budget: {options.budget}")


def _append_index(lines: list[str], document: ContextDocument) -> None:
    lines.extend(["", "## Index", ""])
    index = document.index
    lines.append(
        f"- prompts: {index['prompts']}; notes: {index['notes']}; "
        f"comments: {index['comments']}; versions: {index['versions']}; "
        f"usage: {index['usage']}; files: {index['files']}"
    )
    lines.append("")


def _append_prompt_sections(lines: list[str], document: ContextDocument) -> None:
    options = document.options
    lines.extend(["## Prompts", ""])
    if not document.prompts:
        lines.extend(["_No prompts in scope._", ""])
    for prompt in document.prompts:
        _append_prompt(lines, prompt)
        if "comments" in options.includes:
            _append_prompt_comments(lines, prompt)
        if "versions" in options.includes:
            _append_prompt_versions(lines, prompt)


def _append_prompt(lines: list[str], prompt) -> None:
    lines.extend(
        [
            f"### {prompt.name}",
            "",
            f"- project: {prompt.project_name or 'unbound'}",
            f"- tags: {', '.join(prompt.tags) or '-'}",
            f"- created_at: {prompt.created_at}",
            f"- updated_at: {prompt.updated_at}",
            "",
            "```text",
        ]
    )
    lines.append(prompt.body.rstrip("\n"))
    lines.extend(["```", ""])


def _append_prompt_comments(lines: list[str], prompt) -> None:
    lines.extend(["#### Comments", ""])
    if prompt.comments:
        for comment in prompt.comments:
            lines.append(f"- {comment.created_at} [{comment.id}]: {_md_escape(comment.body)}")
    else:
        lines.append("_No comments._")
    lines.append("")


def _append_prompt_versions(lines: list[str], prompt) -> None:
    lines.extend(["#### Versions", ""])
    if not prompt.versions:
        lines.extend(["_No previous versions._", ""])
        return
    for version in prompt.versions:
        lines.extend([f"- {version.created_at} [{version.id}] {version.reason}", "", "```text"])
        lines.append(version.body.rstrip("\n"))
        lines.extend(["```", ""])


def _append_note_sections(lines: list[str], document: ContextDocument) -> None:
    options = document.options
    if "notes" in options.includes:
        lines.extend(["## Notes", ""])
        if not document.notes:
            lines.extend(["_No notes in scope._", ""])
        for note in document.notes:
            _append_note(lines, note)
            if "versions" in options.includes:
                _append_note_versions(lines, note)


def _append_note(lines: list[str], note) -> None:
    lines.extend(
        [
            f"### {note.title or 'Untitled note'} [{note.id}]",
            "",
            f"- project: {note.project_name or 'unbound'}",
            f"- created_at: {note.created_at}",
            f"- updated_at: {note.updated_at}",
            "",
            "```text",
        ]
    )
    lines.append(note.body.rstrip("\n"))
    lines.extend(["```", ""])


def _append_note_versions(lines: list[str], note) -> None:
    lines.extend(["#### Note Versions", ""])
    if not note.versions:
        lines.extend(["_No previous versions._", ""])
        return
    for version in note.versions:
        lines.extend([f"- {version.created_at} [{version.id}] {version.title or '-'}", "", "```text"])
        lines.append(version.body.rstrip("\n"))
        lines.extend(["```", ""])


def _append_file_sections(lines: list[str], document: ContextDocument) -> None:
    if document.files:
        lines.extend(["## Files", ""])
        for file in document.files:
            _append_file(lines, file)
            _append_file_body(lines, file)


def _append_file(lines: list[str], file) -> None:
    lines.extend(
        [
            f"### {file.path}",
            "",
            f"- id: {file.id}",
            f"- modules: {', '.join(file.module_names) or '-'}",
            f"- kind: {file.kind}",
            f"- status: {file.status}",
            f"- size_bytes: {file.size_bytes}",
            f"- mtime: {file.mtime}",
            f"- sha256: {file.sha256}",
            f"- indexed_at: {file.indexed_at}",
            f"- tokens: {file.token_count}",
            f"- lines: {file.line_count}",
            f"- characters: {file.char_count}",
            f"- findings: {file.finding_count}",
            "",
        ]
    )


def _append_usage(lines: list[str], document: ContextDocument) -> None:
    options = document.options
    if "usage" in options.includes:
        lines.extend(["## Usage Timeline", ""])
        if document.usage:
            lines.extend(["| when | action | prompts | detail |", "| --- | --- | --- | --- |"])
            for event in document.usage:
                lines.append(
                    f"| {_md_escape(event.used_at)} | {_md_escape(str(event.action))} | "
                    f"{_md_escape(', '.join(event.prompt_names) or '-')} | {_md_escape(event.detail or '-')} |"
                )
        else:
            lines.append("_No usage in scope._")
        lines.append("")


def render_context_markdown(document: ContextDocument) -> str:
    lines: list[str] = ["# Prompt Deck Context", "", "## Metadata", ""]
    _append_metadata(lines, document)
    _append_index(lines, document)
    _append_module_map(lines, document)
    _append_prompt_sections(lines, document)
    _append_note_sections(lines, document)
    _append_file_sections(lines, document)
    _append_usage(lines, document)
    return "\n".join(lines).rstrip() + "\n"


def _compact_file_groups(document: ContextDocument):
    assigned_ids: set[int] = set()
    for module in document.modules:
        files = [file for file in document.files if module.name in file.module_names]
        if files:
            assigned_ids.update(file.id for file in files)
            yield module.name, files
    unassigned = [file for file in document.files if file.id not in assigned_ids]
    if unassigned:
        yield "Unassigned", unassigned


def _append_compact_prompts(lines: list[str], document: ContextDocument) -> None:
    options = document.options
    if document.prompts:
        lines.extend(["## Prompts", ""])
        for prompt in document.prompts:
            lines.extend([f"### {prompt.name}", "```text", prompt.body.rstrip("\n"), "```", ""])
            if "comments" in options.includes and prompt.comments:
                lines.append("comments:")
                for comment in prompt.comments:
                    lines.append(f"- {comment.created_at} [{comment.id}]: {_md_escape(comment.body)}")
                lines.append("")
            if "versions" in options.includes and prompt.versions:
                lines.append("versions:")
                for version in prompt.versions:
                    lines.extend([f"- {version.created_at} [{version.id}] {version.reason}", "```text"])
                    lines.append(version.body.rstrip("\n"))
                    lines.extend(["```", ""])


def _append_compact_notes(lines: list[str], document: ContextDocument) -> None:
    options = document.options
    if "notes" in options.includes and document.notes:
        lines.extend(["## Notes", ""])
        for note in document.notes:
            lines.extend(
                [
                    f"### {note.title or 'Untitled note'} [{note.id}]",
                    "```text",
                    note.body.rstrip("\n"),
                    "```",
                    "",
                ]
            )
            if "versions" in options.includes and note.versions:
                lines.append("versions:")
                for version in note.versions:
                    lines.extend([f"- {version.created_at} [{version.id}] {version.title or '-'}", "```text"])
                    lines.append(version.body.rstrip("\n"))
                    lines.extend(["```", ""])


def _append_compact_files(lines: list[str], document: ContextDocument) -> None:
    if document.files:
        lines.extend(["## Files", ""])
        for group_name, files in _compact_file_groups(document):
            if document.modules:
                lines.extend([f"### Module: {group_name}", ""])
            for file in files:
                lines.append(f"#### {file.path}")
                if file.module_names:
                    lines.append(f"modules: {', '.join(file.module_names)}")
                lines.append(f"kind: {file.kind}; tokens: {file.token_count}; lines: {file.line_count}")
                lines.append("```text")
                lines.append(((file.text if file.detail == "full" else file.summary) or "").rstrip("\n"))
                lines.extend(["```", ""])


def _append_compact_usage(lines: list[str], document: ContextDocument) -> None:
    options = document.options
    if "usage" in options.includes and document.usage:
        lines.extend(["## Usage", ""])
        for event in document.usage:
            lines.append(f"- {event.used_at}: {event.action} ({', '.join(event.prompt_names) or '-'})")
        lines.append("")


def render_context_compact_markdown(document: ContextDocument) -> str:
    options = document.options
    project = options.project_name or ("all" if not options.project_filter else "unbound")
    lines: list[str] = ["# Prompt Deck Context", f"project: {project}; files: {len(document.files)}"]
    if options.budget is not None:
        lines[1] += f"; budget: {options.budget}"
    lines.append("")

    _append_module_map(lines, document)
    _append_compact_prompts(lines, document)
    _append_compact_notes(lines, document)
    _append_compact_files(lines, document)
    _append_compact_usage(lines, document)
    return "\n".join(lines).rstrip() + "\n"


def render_context_json(document: ContextDocument) -> str:
    payload = {
        "metadata": {
            "database": document.options.database,
            "project": document.options.project_name if document.options.project_filter else "all",
            "unbound": document.options.project_filter and document.options.project_id is None,
            "include": sorted(document.options.includes),
            "since": document.options.since,
            "budget": document.options.budget,
            "compact": document.options.compact,
        },
        "index": document.index,
        "modules": [
            {
                "name": module.name,
                "description": module.description,
                "dirs": list(module.dirs),
                "files": list(module.files),
                "include": list(module.include_patterns),
                "exclude": list(module.exclude_patterns),
                "depends_on": list(module.depends_on),
            }
            for module in document.modules
        ],
        "prompts": [
            {
                "name": prompt.name,
                "body": prompt.body,
                "created_at": prompt.created_at,
                "updated_at": prompt.updated_at,
                "project_name": prompt.project_name,
                "tags": list(prompt.tags),
                "comments": [
                    {
                        "id": comment.id,
                        "prompt_name": comment.prompt_name,
                        "body": comment.body,
                        "created_at": comment.created_at,
                    }
                    for comment in prompt.comments
                ],
                "versions": [
                    version.model_dump(mode="json") if hasattr(version, "model_dump") else version
                    for version in prompt.versions
                ],
            }
            for prompt in document.prompts
        ],
        "notes": [
            {
                "id": note.id,
                "title": note.title,
                "body": note.body,
                "created_at": note.created_at,
                "updated_at": note.updated_at,
                "project_name": note.project_name,
                "versions": [
                    version.model_dump(mode="json") if hasattr(version, "model_dump") else version
                    for version in note.versions
                ],
            }
            for note in document.notes
        ],
        "usage": [
            event.model_dump(mode="json") if hasattr(event, "model_dump") else event
            for event in document.usage
        ],
        "files": [
            {
                "id": file.id,
                "path": file.path,
                "kind": file.kind,
                "size_bytes": file.size_bytes,
                "mtime": file.mtime,
                "sha256": file.sha256,
                "indexed_at": file.indexed_at,
                "status": file.status,
                "token_count": file.token_count,
                "line_count": file.line_count,
                "char_count": file.char_count,
                "finding_count": file.finding_count,
                "detail": file.detail,
                "summary": file.summary,
                "text": file.text,
                "modules": list(file.module_names),
            }
            for file in document.files
        ],
    }
    return json.dumps(payload, indent=2) + "\n"
