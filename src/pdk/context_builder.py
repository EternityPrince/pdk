from __future__ import annotations

from typing import Any

from .context_files import collect_context_files
from .context_models import ContextComment, ContextDocument, ContextNote, ContextOptions, ContextPrompt
from .file_index import FileIndex


def _is_since(value: str, since: str | None) -> bool:
    return since is None or value >= since


def _context_comment(item: Any) -> ContextComment:
    return ContextComment(
        id=item.id,
        prompt_name=item.prompt_name,
        body=item.body,
        created_at=item.created_at,
    )


def build_context_document(store: Any, options: ContextOptions) -> ContextDocument:
    prompts = sorted(
        store.list(project_id=options.project_id, project_filter=options.project_filter),
        key=lambda item: item.name.casefold(),
    )
    notes = [
        note
        for note in store.notes(project_id=options.project_id, project_filter=options.project_filter)
        if _is_since(note.updated_at, options.since)
    ]

    comments_by_prompt: dict[str, tuple[ContextComment, ...]] = {prompt.name: () for prompt in prompts}
    if "comments" in options.includes:
        comments_by_prompt = {
            prompt.name: tuple(
                _context_comment(item)
                for item in sorted(store.feedback(prompt.name), key=lambda item: (item.created_at, item.id))
                if _is_since(item.created_at, options.since)
            )
            for prompt in prompts
        }

    versions_by_prompt: dict[str, tuple[Any, ...]] = {prompt.name: () for prompt in prompts}
    note_versions_by_id: dict[int, tuple[Any, ...]] = {note.id: () for note in notes}
    if "versions" in options.includes:
        versions_by_prompt = {
            prompt.name: tuple(
                version
                for version in sorted(store.versions(prompt.name), key=lambda item: (item.created_at, item.id))
                if _is_since(version.created_at, options.since)
            )
            for prompt in prompts
        }
        note_versions_by_id = {
            note.id: tuple(
                version
                for version in sorted(store.note_versions(note.id), key=lambda item: (item.created_at, item.id))
                if _is_since(version.created_at, options.since)
            )
            for note in notes
        }

    usage: tuple[Any, ...] = ()
    if "usage" in options.includes:
        usage = tuple(
            sorted(
                (
                    event
                    for event in store.usage(
                        limit=100000,
                        project_id=options.project_id,
                        project_filter=options.project_filter,
                    )
                    if _is_since(event.used_at, options.since)
                ),
                key=lambda item: (item.used_at, item.id),
            )
        )

    files = collect_context_files(FileIndex(), options)
    context_prompts = tuple(
        ContextPrompt(
            name=prompt.name,
            body=prompt.body,
            created_at=prompt.created_at,
            updated_at=prompt.updated_at,
            project_name=prompt.project_name,
            tags=prompt.tags,
            comments=comments_by_prompt[prompt.name],
            versions=versions_by_prompt[prompt.name],
        )
        for prompt in prompts
    )
    context_notes = tuple(
        ContextNote(
            id=note.id,
            title=note.title,
            body=note.body,
            created_at=note.created_at,
            updated_at=note.updated_at,
            project_name=note.project_name,
            versions=note_versions_by_id[note.id],
        )
        for note in notes
    )
    version_count = sum(len(prompt.versions) for prompt in context_prompts)
    version_count += sum(len(note.versions) for note in context_notes)
    return ContextDocument(
        options=options,
        modules=options.modules,
        prompts=context_prompts,
        notes=context_notes,
        usage=usage,
        files=files,
        index={
            "prompts": len(context_prompts),
            "notes": len(context_notes),
            "comments": sum(len(prompt.comments) for prompt in context_prompts),
            "versions": version_count,
            "usage": len(usage),
            "files": len(files),
        },
    )
