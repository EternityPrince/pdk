from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from .editor import EditorError, TextEditor
from .interactive import InteractiveBrowser
from .models import Prompt, TagSet, UsageAction
from .project import ProjectNotFoundError, ProjectResolver
from .store import PromptExistsError, PromptNotFoundError, PromptStore
from .templating import find_variables, render_template
from .ui import ConsoleStyle, PromptFormatter, StatusReporter


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


def _fill_variables(body: str, stderr: TextIO) -> str:
    editor = TextEditor.from_environment()
    values: dict[str, str] = {}
    for name in find_variables(body):
        print(f"Value for {{{{{name}}}}}: opening $EDITOR", file=stderr, flush=True)
        values[name] = editor.edit("")
    return render_template(body, values)


def cmd_add(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    body = TextEditor.from_environment().read_or_edit(stdin)
    tags = _split_tags(args.tag)
    try:
        store.add(args.name, body, replace=args.replace, tags=tags)
    except PromptExistsError as exc:
        raise CliError(f"prompt already exists: {exc.args[0]}") from exc
    suffix = f" with tags: {', '.join(tags)}" if tags else ""
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
    stdout.write(_fill_variables(prompt.body, stderr))
    store.record_usage(UsageAction.SHOW, [args.name])
    return 0


def _write_prompt_rows(prompts: list[Prompt], stdout: TextIO, formatter: PromptFormatter) -> None:
    for prompt in prompts:
        stdout.write(formatter.prompt_row(prompt))


def cmd_list(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    formatter = PromptFormatter(ConsoleStyle(args.color, stdout))
    prompts = store.list(tags=_split_tags(args.tag), query=args.query)
    _write_prompt_rows(prompts, stdout, formatter)
    return 0


def cmd_find(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    store = _store(args)
    formatter = PromptFormatter(ConsoleStyle(args.color, stdout))
    prompts = store.list(tags=_split_tags(args.tag), query=args.query)
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
    for tag in store.tags():
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
    rows = store.stats(args.name)
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
    stdout.write(f"{style.paint('when', 'bold')}\taction\tprompts\tdetail\n")
    for event in store.usage(args.name, limit=args.limit):
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
    browser = InteractiveBrowser(
        _store(args),
        TextEditor.from_environment(),
        stdin,
        stdout,
        color=args.color,
        initial_query=args.query,
        initial_tags=tuple(_split_tags(args.tag)),
    )
    return browser.run()


def cmd_project_init(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    context = ProjectResolver().initialize(Path(args.path) if args.path else None)
    _reporter(args, stderr).success(f"Initialized project prompt store at {context.database_path}")
    return 0


def cmd_project_status(args: argparse.Namespace, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    context = _context(args)
    stdout.write(f"scope\t{context.scope}\n")
    stdout.write(f"database\t{context.database_path}\n")
    if context.project_root is not None:
        stdout.write(f"project\t{context.project_root}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pmpt",
        description="Store prompts globally and print them for shell pipelines.",
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
        help="choose prompt store; auto uses .pmpt when present",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="add a prompt")
    add.add_argument("name")
    add.add_argument("--replace", action="store_true", help="replace an existing prompt")
    add.add_argument("--tag", action="append", help="attach a tag; repeat or use comma-separated tags")
    add.set_defaults(func=cmd_add)

    edit = subparsers.add_parser("edit", help="edit an existing prompt")
    edit.add_argument("name")
    edit.set_defaults(func=cmd_edit)

    show = subparsers.add_parser("show", help="print a prompt")
    show.add_argument("name")
    show.set_defaults(func=cmd_show)

    list_cmd = subparsers.add_parser("list", help="list prompts")
    list_cmd.add_argument("--tag", action="append", help="filter by tag; repeat for all required tags")
    list_cmd.add_argument("--query", help="filter by name, body, or tag text")
    list_cmd.set_defaults(func=cmd_list)

    find = subparsers.add_parser("find", help="search prompts by text and tags")
    find.add_argument("query")
    find.add_argument("--tag", action="append", help="filter by tag; repeat for all required tags")
    find.set_defaults(func=cmd_find)

    tags = subparsers.add_parser("tags", help="show tag aggregation")
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
    stats.set_defaults(func=cmd_stats)

    usage = subparsers.add_parser("usage", help="show detailed usage events")
    usage.add_argument("name", nargs="?")
    usage.add_argument("--limit", type=int, default=50)
    usage.set_defaults(func=cmd_usage)

    versions = subparsers.add_parser("versions", help="inspect or clean previous prompt versions")
    versions.add_argument("name")
    versions.add_argument("--show", type=int, metavar="ID", help="print a previous version")
    versions.add_argument("--prune", action="store_true", help="delete previous versions")
    versions.add_argument("--yes", action="store_true", help="confirm pruning")
    versions.set_defaults(func=cmd_versions)

    feedback = subparsers.add_parser("feedback", help="attach or list feedback for a prompt")
    feedback.add_argument("name")
    feedback.add_argument("--list", action="store_true", help="list existing feedback")
    feedback.set_defaults(func=cmd_feedback)

    browse = subparsers.add_parser("browse", help="interactive prompt browser")
    browse.add_argument("--tag", action="append", help="start with a tag filter")
    browse.add_argument("--query", help="start with a text search")
    browse.set_defaults(func=cmd_browse)

    project = subparsers.add_parser("project", help="manage project-local prompt storage")
    project_subparsers = project.add_subparsers(dest="project_command", required=True)
    project_init = project_subparsers.add_parser("init", help="initialize .pmpt in a folder")
    project_init.add_argument("path", nargs="?", help="project folder; defaults to cwd")
    project_init.set_defaults(func=cmd_project_init)
    project_status = project_subparsers.add_parser("status", help="show active prompt store")
    project_status.set_defaults(func=cmd_project_status)

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
    except (CliError, PromptNotFoundError, ProjectNotFoundError, EditorError, ValidationError) as exc:
        if isinstance(exc, PromptNotFoundError):
            message = f"prompt not found: {exc.args[0]}"
        elif isinstance(exc, ValidationError):
            message = exc.errors()[0]["msg"]
        else:
            message = str(exc)
        _reporter(args, sys.stderr).error(message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
