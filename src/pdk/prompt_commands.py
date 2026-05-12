from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from typing import TextIO

from .command_support import (
    CliError,
    _context,
    _fill_variables,
    _project_selection,
    _reporter,
    _short_timestamp,
    _split_tags,
    _store,
    _warn_secrets,
    _write_token_summary,
)
from .completions import bash_completion, fish_completion, zsh_completion
from .editor import TextEditor
from .file_index import FileIndex
from .interactive import Clipboard, InteractiveBrowser
from .models import Prompt, PromptStats, UsageAction
from .prompt_hygiene import duplicate_groups, stale_prompts
from .store import PromptExistsError, PromptStore
from .tokens import count_tokens
from .ui import ConsoleStyle, PromptFormatter


def cmd_add(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    body = TextEditor.from_environment().read_or_edit(stdin)
    _warn_secrets(args, stderr, args.name, body)
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
    _warn_secrets(args, stderr, args.name, updated)
    store.update(args.name, updated)
    _reporter(args, stderr).success(f"Updated {args.name}")
    return 0


def cmd_show(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    prompt = store.get(args.name)
    rendered = _fill_variables(args, prompt.body, stdin, stderr)
    stdout.write(rendered)
    _write_token_summary(prompt.body, rendered, stdout, stderr)
    store.record_usage(UsageAction.SHOW, [args.name])
    return 0


def _copy_prompt_to_clipboard(
    args: argparse.Namespace,
    store: PromptStore,
    prompt: Prompt,
    stdin: TextIO,
    stderr: TextIO,
    *,
    detail: str,
) -> None:
    body = prompt.body if getattr(args, "raw", False) else _fill_variables(args, prompt.body, stdin, stderr)
    try:
        copied = Clipboard().copy(body)
    except subprocess.CalledProcessError as exc:
        raise CliError("clipboard command failed") from exc
    if not copied:
        raise CliError("clipboard command is not available")
    store.record_usage(UsageAction.BROWSE, [prompt.name], detail=detail)
    _reporter(args, stderr).success(f"Copied {prompt.name}")


def cmd_clip(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    prompt = store.get(args.name)
    _copy_prompt_to_clipboard(args, store, prompt, stdin, stderr, detail=args.command)
    return 0


def _write_prompt_rows(prompts: list[Prompt], stdout: TextIO, formatter: PromptFormatter) -> None:
    for prompt in prompts:
        stdout.write(formatter.prompt_row(prompt))


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
    headers = ("prompt", "tokens", "uses", "edits", "feedback", "last used", "tags")
    rows = []
    for prompt in ordered:
        stats = stats_by_name.get(prompt.name)
        rows.append(
            (
                prompt.name,
                str(count_tokens(prompt.body)),
                str(stats.show_count if stats else 0),
                str(stats.edit_count if stats else 0),
                str(stats.feedback_count if stats else 0),
                _short_timestamp(stats.last_used_at if stats else None),
                " ".join(f"#{tag}" for tag in prompt.tags) or "-",
            )
        )
    widths = [max([len(headers[index]), *(len(row[index]) for row in rows)]) for index in range(len(headers) - 1)]
    aligns = ("left", "right", "right", "right", "right", "left")

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
    stats_by_name = {stats.name: stats for stats in store.stats(project_id=project_id, project_filter=project_filter)}
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
    stdout.write(f"{style.paint('prompt', 'bold')}\tshows\tedits\tfeedback\tlast used\n")
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
        stdout.write(f"{event.used_at}\t{style.paint(event.action, 'magenta')}\t{prompts}\t{event.detail or '-'}\n")
    return 0


def _prompt_scope(args: argparse.Namespace, store: PromptStore) -> tuple[list[Prompt], dict[str, PromptStats]]:
    project_id, project_filter, _ = _project_selection(args, store)
    prompts = store.list(project_id=project_id, project_filter=project_filter)
    stats_by_name = {stats.name: stats for stats in store.stats(project_id=project_id, project_filter=project_filter)}
    return prompts, stats_by_name


def cmd_doctor(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    context = _context(args)
    store = PromptStore(context.database_path)
    prompts, stats_by_name = _prompt_scope(args, store)
    projects = store.projects()
    project_id, project_filter, _ = _project_selection(args, store)
    notes = store.notes(project_id=project_id, project_filter=project_filter)
    duplicates = duplicate_groups(prompts)
    stale = stale_prompts(prompts, stats_by_name, days=args.days)
    untagged = sum(1 for prompt in prompts if not prompt.tags)
    indexed_without_summaries = sum(1 for file in FileIndex().files() if not file.summary)
    stdout.write(f"database\t{context.database_path}\n")
    stdout.write(f"scope\t{context.scope}\n")
    stdout.write(f"prompts\t{len(prompts)}\n")
    stdout.write(f"projects\t{len(projects)}\n")
    stdout.write(f"notes\t{len(notes)}\n")
    stdout.write(f"untagged\t{untagged}\n")
    stdout.write(f"unbound\t{sum(1 for prompt in prompts if prompt.project_id is None)}\n")
    stdout.write(f"duplicate_groups\t{len(duplicates)}\n")
    stdout.write(f"stale\t{len(stale)}\n")
    stdout.write("\nRecommendations\n")
    if untagged > 0:
        stdout.write(f"- {untagged} prompts have no tags. Add tags with: pdk tag add NAME TAG\n")
    if len(duplicates) > 0:
        stdout.write(f"- {len(duplicates)} duplicate prompt groups found. Inspect with: pdk duplicates\n")
    if len(stale) > 0:
        stdout.write(f"- {len(stale)} prompts look stale. Inspect with: pdk stale --days DAYS\n")
    if indexed_without_summaries > 0:
        stdout.write(f"- {indexed_without_summaries} indexed files have no summaries. Run: pdk digest\n")
    if context.scope == "project" and context.project_root is not None:
        context_config = Path(context.project_root) / ".pdk" / "context.toml"
        if not context_config.exists():
            stdout.write("- No context config found. Run: pdk project init\n")
    return 0


def cmd_duplicates(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    prompts, _ = _prompt_scope(args, store)
    groups = duplicate_groups(prompts)
    style = ConsoleStyle(args.color, stdout)
    formatter = PromptFormatter(style)
    stdout.write("group\tprompt\tproject\ttokens\tpreview\n")
    for index, group in enumerate(groups, 1):
        for prompt in group:
            stdout.write(
                f"{index}\t{prompt.name}\t{prompt.project_name or 'unbound'}\t"
                f"{count_tokens(prompt.body)}\t{formatter.preview(prompt.body, 80)}\n"
            )
    return 0


def cmd_stale(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    prompts, stats_by_name = _prompt_scope(args, store)
    stale = stale_prompts(prompts, stats_by_name, days=args.days)
    stdout.write("prompt\tupdated\tlast used\tuses\ttags\n")
    for prompt in stale:
        stats = stats_by_name.get(prompt.name)
        stdout.write(
            f"{prompt.name}\t{_short_timestamp(prompt.updated_at)}\t"
            f"{_short_timestamp(stats.last_used_at if stats else None)}\t"
            f"{stats.show_count if stats else 0}\t{', '.join(prompt.tags) or '-'}\n"
        )
    return 0


def cmd_rename(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    try:
        store.rename_prompt(args.old, args.new)
    except PromptExistsError as exc:
        raise CliError(f"prompt already exists: {exc.args[0]}") from exc
    _reporter(args, stderr).success(f"Renamed {args.old} to {args.new}")
    return 0


def cmd_move(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    target = None if args.no_project else args.project
    store.move_prompts(args.names, target)
    destination = "unbound prompts" if target is None else f"project {target}"
    _reporter(args, stderr).success(f"Moved {len(args.names)} prompt(s) to {destination}")
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
                f"{style.paint(str(item.id), 'yellow')}\t{item.created_at}\t{formatter.preview(item.body, 120)}\n"
            )
        return 0

    body = TextEditor.from_environment().read_or_edit(stdin)
    _warn_secrets(args, stderr, f"feedback for {args.name}", body)
    store.add_feedback(args.name, body)
    _reporter(args, stderr).success(f"Saved feedback for {args.name}")
    return 0


def _run_fzf(prompts: list[Prompt]) -> str | None:
    if shutil.which("fzf") is None:
        raise CliError("fzf is not installed")
    lines = [
        "\t".join(
            (
                prompt.name,
                prompt.project_name or "unbound",
                " ".join(f"#{tag}" for tag in prompt.tags) or "-",
            )
        )
        for prompt in prompts
    ]
    try:
        result = subprocess.run(
            ["fzf", "--with-nth=1,2,3", "--delimiter=\t"],
            input="\n".join(lines),
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise CliError(f"fzf failed: {exc}") from exc
    if result.returncode == 130 or not result.stdout.strip():
        return None
    if result.returncode != 0:
        raise CliError((result.stderr or "fzf failed").strip())
    return result.stdout.split("\t", 1)[0].strip()


def _run_fzf_browser(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    project_id, project_filter, _ = _project_selection(args, store)
    prompts = store.list(
        tags=_split_tags(args.tag),
        query=args.query,
        project_id=project_id,
        project_filter=project_filter,
    )
    if not prompts:
        raise CliError("no prompts match the active filters")
    selected = _run_fzf(prompts)
    if selected is None:
        return 0
    prompt = store.get(selected)
    _copy_prompt_to_clipboard(args, store, prompt, stdin, stderr, detail="fzf")
    return 0


def cmd_browse(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    if args.fzf:
        return _run_fzf_browser(args, stdin, stdout, stderr)
    store = _store(args)
    project_id, project_filter, _ = _project_selection(args, store)
    editor = TextEditor.from_environment()
    initial_tags = tuple(_split_tags(args.tag))
    if args.plain or not stdin.isatty() or not stdout.isatty():
        browser = InteractiveBrowser(
            store,
            editor,
            stdin,
            stdout,
            color=args.color,
            initial_query=args.query,
            initial_tags=initial_tags,
            project_id=project_id,
            project_filter=project_filter,
        )
        return browser.run()

    try:
        from .tui import run_tui_browser
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing.split(".", 1)[0] not in {"textual", "rich"}:
            raise
        _reporter(args, stderr).warning(
            f"fullscreen browse is unavailable because {missing} is not installed; using --plain"
        )
        browser = InteractiveBrowser(
            store,
            editor,
            stdin,
            stdout,
            color=args.color,
            initial_query=args.query,
            initial_tags=initial_tags,
            project_id=project_id,
            project_filter=project_filter,
        )
        return browser.run()

    return run_tui_browser(
        store,
        editor,
        initial_query=args.query,
        initial_tags=initial_tags,
        project_id=project_id,
        project_filter=project_filter,
    )


def cmd_completions(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    if args.shell == "bash":
        stdout.write(bash_completion())
    elif args.shell == "zsh":
        stdout.write(zsh_completion())
    else:
        stdout.write(fish_completion())
    return 0
