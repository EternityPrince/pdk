from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any, TextIO

from .command_support import CliError, _reporter, _store
from .context_builder import build_context_document
from .context_config import context_options_from_args
from .context_models import ContextDocument, ContextOptions
from .context_rendering import render_context_compact_markdown, render_context_json, render_context_markdown
from .interactive import Clipboard
from .privacy import redact_private_data
from .security import secret_warnings
from .tokens import count_tokens


def _warn_context_secrets(args: argparse.Namespace, document, stderr: TextIO) -> None:
    findings: set[str] = set()
    for prompt in document.prompts:
        findings.update(secret_warnings(prompt.body))
        for comment in prompt.comments:
            findings.update(secret_warnings(comment.body))
        for version in prompt.versions:
            findings.update(secret_warnings(version.body))
    for note in document.notes:
        findings.update(secret_warnings(note.body))
        for version in note.versions:
            findings.update(secret_warnings(version.body))
    if findings:
        _reporter(args, stderr).warning(
            "context may contain secret-like data; use --redact to mask: " + ", ".join(sorted(findings))
        )


def _redact_text(value: str | None, options: ContextOptions) -> str | None:
    if value is None:
        return None
    return redact_private_data(
        value,
        profile=options.privacy_profile,
        use_model=options.privacy_model,
        model_name=options.privacy_model_name,
        model_threshold=options.privacy_model_threshold,
    )


def _redact_model(item: Any, options: ContextOptions) -> Any:
    updates = {}
    for field in ("body", "detail"):
        value = getattr(item, field, None)
        if isinstance(value, str):
            updates[field] = _redact_text(value, options)
    if not updates:
        return item
    if hasattr(item, "model_copy"):
        return item.model_copy(update=updates)
    return replace(item, **updates)


def _redact_document(document: ContextDocument) -> ContextDocument:
    options = document.options
    prompts = tuple(
        replace(
            prompt,
            body=_redact_text(prompt.body, options) or "",
            comments=tuple(
                replace(comment, body=_redact_text(comment.body, options) or "")
                for comment in prompt.comments
            ),
            versions=tuple(_redact_model(version, options) for version in prompt.versions),
        )
        for prompt in document.prompts
    )
    notes = tuple(
        replace(
            note,
            body=_redact_text(note.body, options) or "",
            versions=tuple(_redact_model(version, options) for version in note.versions),
        )
        for note in document.notes
    )
    files = tuple(
        replace(
            file,
            summary=_redact_text(file.summary, options),
            text=_redact_text(file.text, options),
        )
        for file in document.files
    )
    usage = tuple(_redact_model(event, options) for event in document.usage)
    return replace(document, prompts=prompts, notes=notes, files=files, usage=usage)


def _render(args: argparse.Namespace, document: ContextDocument) -> str:
    if args.format == "json":
        return render_context_json(document)
    if document.options.compact:
        return render_context_compact_markdown(document)
    return render_context_markdown(document)


def _warn_budget(args: argparse.Namespace, stderr: TextIO, *, tokens: int, budget: int | None) -> None:
    if budget is not None and tokens > budget:
        _reporter(args, stderr).warning(f"context token budget exceeded: {tokens} > {budget}")


def _write_dry_run(args: argparse.Namespace, document: ContextDocument, rendered: str, stdout: TextIO) -> None:
    tokens = count_tokens(rendered)
    comments = sum(len(prompt.comments) for prompt in document.prompts)
    stdout.write("context dry run\n")
    stdout.write(f"prompts\t{len(document.prompts)}\n")
    stdout.write(f"notes\t{len(document.notes)}\n")
    stdout.write(f"comments\t{comments}\n")
    stdout.write(f"files\t{len(document.files)}\n")
    stdout.write("file_sources\t" + (", ".join(file.path for file in document.files) if document.files else "-") + "\n")
    stdout.write(f"file_detail\t{document.options.file_detail}\n")
    stdout.write(f"compact\t{'yes' if document.options.compact else 'no'}\n")
    if document.modules:
        stdout.write("modules\t" + ", ".join(module.name for module in document.modules) + "\n")
    stdout.write(f"estimated_tokens\t{tokens}\n")
    if document.options.budget is not None:
        status = "over" if tokens > document.options.budget else "within"
        stdout.write(f"budget\t{document.options.budget}\n")
        stdout.write(f"budget_status\t{status}\n")


def cmd_context(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    if args.dry_run and args.copy:
        raise CliError("--dry-run cannot be combined with --copy")
    store = _store(args)
    options = context_options_from_args(args, store)
    document = build_context_document(store, options)
    if options.redact:
        document = _redact_document(document)
    else:
        _warn_context_secrets(args, document, stderr)
    rendered = _render(args, document)
    tokens = count_tokens(rendered)
    _warn_budget(args, stderr, tokens=tokens, budget=options.budget)
    if args.dry_run:
        _write_dry_run(args, document, rendered, stdout)
        return 0
    if args.copy:
        try:
            copied = Clipboard().copy(rendered)
        except Exception as exc:
            raise CliError("clipboard command failed") from exc
        if not copied:
            raise CliError("clipboard command is not available")
        _reporter(args, stderr).success(f"Copied context to clipboard ({tokens} tokens)")
        return 0
    if args.output:
        Path(args.output).expanduser().write_text(rendered, encoding="utf-8")
        _reporter(args, stderr).success(f"Wrote context {args.output}")
        return 0
    stdout.write(rendered)
    return 0
